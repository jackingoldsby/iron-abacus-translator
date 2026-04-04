"""CLI entry point for Cobalt Loom web scraping."""

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm

from cache.disk_cache import DiskCache
from catalog.lookup import get_work_info, get_works_needing_scraping, get_scrape_status
from catalog.registrar import register_work_file, update_work_link
from config.defaults import DEFAULT_CACHE_DIR, DEFAULT_DB_PATH, DEFAULT_OUTPUT_DIR
from config.work_urls import WORK_URLS
from models.core import ScrapedWork, ScrapeReport
from scrapers.wikisource_scraper import WikisourceScraper
from scrapers.ctext_scraper import CtextScraper
from structurers.chapter_detector import validate_chapters
from structurers.json_emitter import generate_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def cmd_list(args):
    """List works needing scraping."""
    works = get_works_needing_scraping(args.db_path)
    if not works:
        logger.info("All works have files — nothing to scrape.")
        return 0

    logger.info(f"Works needing scraping: {len(works)}")
    for w in works:
        urls = WORK_URLS.get(w["work_number"], {})
        source = "wikisource" if "wikisource" in urls else ("ctext" if "ctext" in urls else "NO URL")
        logger.info(
            f"  {w['work_number']:6s} {w['title_chinese']:20s} {w['author_chinese']:10s} "
            f"dir=work_{w['directory_number']}  source={source}"
        )
    return 0


def cmd_scrape(args):
    """Scrape one or all works."""
    cache = DiskCache(args.cache_dir) if not args.no_cache else None

    if args.all:
        works = get_works_needing_scraping(args.db_path)
        work_numbers = [w["work_number"] for w in works if w["work_number"] in WORK_URLS]
    elif args.work:
        work_numbers = [args.work]
    else:
        logger.error("Specify --work WORK_NUMBER or --all")
        return 1

    if not work_numbers:
        logger.info("No works to scrape.")
        return 0

    reports = []
    for wn in work_numbers:
        report = scrape_work(
            work_number=wn,
            db_path=args.db_path,
            output_dir=args.output_dir,
            cache=cache,
            dry_run=args.dry_run,
            resume=args.resume,
            use_nimble=getattr(args, 'nimble', True),
        )
        reports.append(report)

    # Summary
    logger.info(f"\n{'='*70}")
    logger.info("SCRAPE SUMMARY")
    logger.info(f"{'='*70}")
    for r in reports:
        status = "DRY RUN" if r.dry_run else ("OK" if not r.errors else "ERRORS")
        logger.info(
            f"  {r.work_number:6s} {r.title:20s} {r.chapters_scraped}/{r.chapters_discovered} ch  "
            f"{r.character_count:,} chars  [{status}]"
        )
        for err in r.errors:
            logger.warning(f"    ERROR: {err}")

    return 0


def scrape_work(
    work_number: str,
    db_path: str,
    output_dir: str,
    cache: DiskCache | None,
    dry_run: bool = False,
    resume: bool = False,
    use_nimble: bool = True,
) -> ScrapeReport:
    """Scrape a single work and emit JSON."""
    report = ScrapeReport(work_number=work_number, dry_run=dry_run)

    # Look up work in catalog
    work_info = get_work_info(db_path, work_number)
    if not work_info:
        report.errors.append(f"Work {work_number} not found in catalog")
        return report

    report.title = work_info["title_chinese"]

    # Look up URL mapping
    urls = WORK_URLS.get(work_number)
    if not urls:
        report.errors.append(f"No URL mapping for {work_number} in config/work_urls.py")
        return report

    logger.info(f"\n{'='*70}")
    logger.info(f"Scraping: {work_number} — {work_info['title_chinese']} ({work_info['author_chinese']})")
    logger.info(f"{'='*70}")

    # Choose scraper
    if "wikisource" in urls:
        scraper = WikisourceScraper(cache=cache, use_nimble=use_nimble)
        page_title = urls["wikisource"]
        report.source = "wikisource"
    elif "ctext" in urls:
        scraper = CtextScraper(cache=cache, use_nimble=use_nimble)
        page_title = urls["ctext"]
        report.source = "ctext"
    else:
        report.errors.append(f"No valid source URL for {work_number}")
        return report

    # Check for existing output (resume mode)
    dir_name = f"work_{work_info['directory_number']}"
    dir_path = Path(output_dir) / dir_name
    existing_json = None
    if resume and dir_path.exists():
        json_files = list(dir_path.glob(f"{work_number}*.json"))
        if json_files:
            existing_json = json_files[0]
            logger.info(f"Resume mode: found existing {existing_json.name}")

    # Discover chapters
    try:
        chapter_ids = scraper.discover_chapters(page_title)
    except Exception as e:
        report.errors.append(f"Failed to discover chapters: {e}")
        scraper.close()
        return report

    report.chapters_discovered = len(chapter_ids)
    logger.info(f"Discovered {len(chapter_ids)} chapters")

    if dry_run:
        for i, ch_id in enumerate(chapter_ids):
            logger.info(f"  [{i+1:3d}] {ch_id}")
        scraper.close()
        return report

    # Load existing chapters for resume
    existing_titles = set()
    if existing_json:
        try:
            data = json.loads(existing_json.read_text(encoding="utf-8"))
            existing_titles = {ch["title"] for ch in data.get("chapters", [])}
            logger.info(f"Resume: {len(existing_titles)} chapters already scraped")
        except Exception:
            pass

    # Filter out already-scraped chapters for resume
    to_scrape = []
    for ch_id in chapter_ids:
        parts = ch_id.rsplit("/", 1) if "/" in ch_id else [ch_id]
        ch_title_hint = parts[-1] if len(parts) > 1 else ch_id
        if ch_title_hint in existing_titles:
            report.chapters_skipped += 1
        else:
            to_scrape.append(ch_id)

    # Scrape chapters — parallel with Nimble, sequential without
    chapters = []
    max_workers = getattr(scraper, 'use_nimble', False) and 40 or 1

    if max_workers > 1:
        logger.info(f"Parallel scraping with {max_workers} workers via Nimble")
        # Each thread needs its own scraper to avoid shared httpx client issues
        results = {}  # ch_id -> ScrapedChapter | None
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(scraper.scrape_chapter, ch_id): ch_id for ch_id in to_scrape}
            with tqdm(total=len(to_scrape), desc=f"Scraping {work_number}", unit="ch") as pbar:
                for future in as_completed(futures):
                    ch_id = futures[future]
                    try:
                        chapter = future.result()
                        if chapter:
                            results[ch_id] = chapter
                            report.chapters_scraped += 1
                        else:
                            report.errors.append(f"Failed to scrape: {ch_id}")
                    except Exception as e:
                        report.errors.append(f"Error scraping {ch_id}: {e}")
                    pbar.update(1)
        # Restore original order
        chapters = [results[ch_id] for ch_id in to_scrape if ch_id in results]
    else:
        for ch_id in tqdm(to_scrape, desc=f"Scraping {work_number}", unit="ch"):
            chapter = scraper.scrape_chapter(ch_id)
            if chapter:
                chapters.append(chapter)
                report.chapters_scraped += 1
            else:
                report.errors.append(f"Failed to scrape: {ch_id}")

    scraper.close()

    if not chapters and not existing_titles:
        report.errors.append("No chapters scraped")
        return report

    # If resuming, merge with existing chapters
    if existing_json and existing_titles:
        try:
            data = json.loads(existing_json.read_text(encoding="utf-8"))
            from models.core import ScrapedChapter
            for ch_data in data.get("chapters", []):
                if ch_data["title"] not in {c.title for c in chapters}:
                    chapters.insert(0, ScrapedChapter(
                        title=ch_data["title"],
                        content=ch_data["content"],
                    ))
        except Exception as e:
            logger.warning(f"Failed to merge existing chapters: {e}")

    # Validate
    warnings = validate_chapters(chapters)
    for w in warnings:
        logger.warning(f"Validation: {w}")

    # Build work
    work = ScrapedWork(
        work_number=work_number,
        title=work_info["title_chinese"],
        author=work_info["author_chinese"],
        chapters=chapters,
        source=report.source,
        source_url=scraper.get_work_url(page_title) if hasattr(scraper, 'get_work_url') else "",
        directory_number=work_info["directory_number"],
    )
    work.compute_character_count()
    report.character_count = work.character_count

    # Emit JSON
    output_data = generate_json(work)

    dir_path.mkdir(parents=True, exist_ok=True)
    safe_author = work_info['author_chinese'].replace("/", "·")
    filename = f"{work_number}_{work_info['title_chinese']}_{safe_author}.json"
    file_path = dir_path / filename

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    logger.info(f"Wrote: {dir_name}/{filename} ({work.character_count:,} chars, {len(chapters)} chapters)")

    # Update catalog
    source_url = scraper.get_work_url(page_title) if hasattr(scraper, 'get_work_url') else ""
    update_work_link(db_path, work_number, source_url)
    register_work_file(
        db_path=db_path,
        work_number=work_number,
        filename=filename,
        full_path=str(file_path),
        directory_name=dir_name,
        character_count=work.character_count,
    )

    return report


def cmd_status(args):
    """Show scraping status for all works."""
    statuses = get_scrape_status(args.db_path)
    if not statuses:
        logger.info("No A-prefix works in catalog.")
        return 0

    logger.info(f"{'Work':6s} {'Title':20s} {'Author':10s} {'Files':5s} {'Chars':>10s} {'Link':s}")
    logger.info("-" * 70)
    for s in statuses:
        link = s["work_link"] or "—"
        if len(link) > 20:
            link = link[:20] + "..."
        logger.info(
            f"{s['work_number']:6s} {s['title']:20s} {s['author']:10s} "
            f"{s['files']:5d} {s['characters']:>10,} {link}"
        )
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Cobalt Loom — Wikisource/ctext.org scraper for classical Chinese novels",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m cli.scrape list
  python -m cli.scrape scrape --work A005 --dry-run
  python -m cli.scrape scrape --work A005
  python -m cli.scrape scrape --all
  python -m cli.scrape status
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # list
    p_list = subparsers.add_parser("list", help="Show works needing scraping")
    p_list.add_argument("--db-path", default=DEFAULT_DB_PATH)

    # scrape
    p_scrape = subparsers.add_parser("scrape", help="Scrape work(s) from web sources")
    p_scrape.add_argument("--work", metavar="WORK_NUMBER", help="Scrape a specific work (e.g., A005)")
    p_scrape.add_argument("--all", action="store_true", help="Scrape all unscraped works")
    p_scrape.add_argument("--dry-run", action="store_true", help="Discover chapters only, no downloads")
    p_scrape.add_argument("--resume", action="store_true", help="Skip already-scraped chapters")
    p_scrape.add_argument("--no-cache", action="store_true", help="Ignore HTML cache")
    p_scrape.add_argument("--nimble", action="store_true", default=True,
                          help="Use Nimble SDK for ctext.org (default: on)")
    p_scrape.add_argument("--no-nimble", dest="nimble", action="store_false",
                          help="Disable Nimble SDK, use direct requests only")
    p_scrape.add_argument("--db-path", default=DEFAULT_DB_PATH)
    p_scrape.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    p_scrape.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)

    # status
    p_status = subparsers.add_parser("status", help="Show scraping progress")
    p_status.add_argument("--db-path", default=DEFAULT_DB_PATH)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "list":
        return cmd_list(args)
    elif args.command == "scrape":
        return cmd_scrape(args)
    elif args.command == "status":
        return cmd_status(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
