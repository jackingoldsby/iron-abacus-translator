"""CLI entry point for ebook ingestion."""

import argparse
import fnmatch
import json
import logging
import sys
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import List, Set, Tuple, Dict

from catalog.dedup import load_catalog, title_matches_catalog
from catalog.registrar import (
    get_next_directory_number,
    get_next_work_number,
    register_works,
)
from config.defaults import DEFAULT_DB_PATH, DEFAULT_EPUB_DIR, DEFAULT_OUTPUT_DIR, VOLUME_LETTERS
from detectors.volume_grouper import group_volumes
from extractors.epub_extractor import EpubExtractor, extract_author_from_epub
from models.core import IngestReport
from transformers.encoding import S2T
from transformers.json_emitter import generate_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def process_epub(
    epub_path: Path,
    catalog_works: List[Dict],
    catalog_authors: Set[str],
    next_work_num: int,
    next_dir_num: int,
    output_dir: str,
    db_path: str,
    dry_run: bool = False,
) -> Tuple[IngestReport, int, int]:
    """Process a single EPUB collection file.

    Returns (report, updated_next_work_num, updated_next_dir_num).
    """
    filename = epub_path.name
    logger.info(f"\n{'='*70}")
    logger.info(f"Processing: {filename[:70]}")
    logger.info(f"{'='*70}")

    report = IngestReport(epub_file=filename, author="")

    extractor = EpubExtractor()

    # Read EPUB for author detection
    try:
        from ebooklib import epub
        book = epub.read_epub(str(epub_path))
    except Exception as e:
        report.errors.append(f"Failed to read EPUB: {e}")
        logger.error(f"  Failed to read EPUB: {e}")
        return report, next_work_num, next_dir_num

    author_simp = extract_author_from_epub(book, filename)
    author_trad = S2T.convert(author_simp) if author_simp else ""
    report.author = f"{author_trad} ({author_simp})" if author_trad != author_simp else author_simp

    logger.info(f"  Author: {report.author}")

    # Extract works
    try:
        detected_works = extractor.extract_works(epub_path, author_hint=author_simp)
    except Exception as e:
        report.errors.append(f"Failed to extract works: {e}")
        logger.error(f"  Failed to extract works: {e}")
        traceback.print_exc()
        return report, next_work_num, next_dir_num

    report.works_detected = len(detected_works)
    logger.info(f"  Detected {len(detected_works)} works/volumes")

    if not detected_works:
        report.errors.append("No works detected")
        return report, next_work_num, next_dir_num

    # Group volumes
    work_groups = group_volumes(detected_works)
    logger.info(f"  Grouped into {len(work_groups)} logical works")

    # Match against catalog
    for group in work_groups:
        match = title_matches_catalog(
            group.base_title_trad, catalog_works, group.author_trad, group.author_simp
        )
        if not match:
            match = title_matches_catalog(
                group.base_title_simp, catalog_works, group.author_trad, group.author_simp
            )
        if match:
            group.is_duplicate = True
            group.matched_catalog_title = match.get("title_chinese", "")
            report.works_duplicate += 1
        else:
            report.works_new += 1

    logger.info(f"  New: {report.works_new}, Duplicates: {report.works_duplicate}")

    # Assign work numbers and directories
    for group in work_groups:
        if group.is_duplicate:
            continue
        group.work_number = f"A{next_work_num:03d}"
        group.directory_number = f"{next_dir_num:04d}"
        next_work_num += 1
        next_dir_num += 1

    # Log details
    for group in work_groups:
        total_chars = sum(v.character_count for v in group.volumes)
        total_chapters = sum(len(v.chapters) for v in group.volumes)
        status = "DUP" if group.is_duplicate else "NEW"
        vol_info = f" ({len(group.volumes)} vols)" if len(group.volumes) > 1 else ""

        detail = {
            "title_trad": group.base_title_trad,
            "title_simp": group.base_title_simp,
            "author": group.author_trad,
            "status": status,
            "volumes": len(group.volumes),
            "chapters": total_chapters,
            "characters": total_chars,
            "work_number": group.work_number,
            "directory": f"work_{group.directory_number}" if group.directory_number else "",
        }
        if group.is_duplicate:
            detail["matched"] = group.matched_catalog_title

        report.work_details.append(detail)
        logger.info(
            f"  [{status}] {group.base_title_trad}{vol_info} "
            f"- {total_chapters} ch, {total_chars:,} chars"
            + (f" (matched: {group.matched_catalog_title})" if group.is_duplicate else
               f" -> {group.work_number} work_{group.directory_number}")
        )

    # Write files and register
    if not dry_run:
        for group in work_groups:
            if group.is_duplicate:
                continue

            dir_name = f"work_{group.directory_number}"
            dir_path = Path(output_dir) / dir_name
            dir_path.mkdir(parents=True, exist_ok=True)

            for i, vol in enumerate(group.volumes):
                vol_letter = VOLUME_LETTERS[i] if len(group.volumes) > 1 else ""
                wn = f"{group.work_number}{vol_letter}"
                filename_json = f"{wn}_{vol.title_traditional}_{vol.author_traditional}.json"
                file_path = dir_path / filename_json

                data = generate_json(vol, wn)

                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                logger.info(f"  Wrote: {dir_name}/{filename_json}")
                report.works_written += 1

        register_works(db_path, work_groups, output_dir, dry_run)
        logger.info(f"  Registered {report.works_new} new works in catalog")

    return report, next_work_num, next_dir_num


def main():
    parser = argparse.ArgumentParser(
        description="Ingest ebook collections into translation pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run on all EPUBs
  cd jade_shuttle && python -m cli.ingest --dry-run

  # Process a single EPUB
  python -m cli.ingest --single "萧逸*.epub" --dry-run

  # Full ingestion
  python -m cli.ingest
        """,
    )
    parser.add_argument(
        "--epub-dir", default=DEFAULT_EPUB_DIR,
        help="Directory containing EPUB files",
    )
    parser.add_argument(
        "--output-dir", default=DEFAULT_OUTPUT_DIR,
        help="Output directory for work_XXXX directories",
    )
    parser.add_argument(
        "--db-path", default=DEFAULT_DB_PATH,
        help="Path to works_translator.duckdb",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report only, no files written or DB changes",
    )
    parser.add_argument(
        "--single", metavar="PATTERN",
        help="Process only EPUBs matching this glob pattern",
    )
    parser.add_argument(
        "--report", metavar="PATH",
        help="Save JSON report to this path",
    )
    args = parser.parse_args()

    epub_dir = Path(args.epub_dir)
    if not epub_dir.exists():
        logger.error(f"EPUB directory not found: {epub_dir}")
        return 1

    # Find EPUB files
    epub_files = sorted(epub_dir.glob("*.epub"))
    if args.single:
        epub_files = [f for f in epub_files if fnmatch.fnmatch(f.name, args.single)]

    if not epub_files:
        logger.error(f"No EPUB files found in {epub_dir}" +
                      (f" matching '{args.single}'" if args.single else ""))
        return 1

    logger.info(f"Found {len(epub_files)} EPUB files to process")
    if args.dry_run:
        logger.info("DRY RUN — no files will be written")

    # Load catalog
    catalog_works, catalog_authors = load_catalog(args.db_path)
    logger.info(f"Catalog: {len(catalog_works)} works, {len(catalog_authors)} authors")

    # Get starting numbers
    next_work_num = get_next_work_number(args.db_path)
    next_dir_num = get_next_directory_number(args.output_dir)
    logger.info(f"Next work number: A{next_work_num:03d}")
    logger.info(f"Next directory: work_{next_dir_num:04d}")

    # Process each EPUB
    all_reports: List[IngestReport] = []
    for epub_path in epub_files:
        report, next_work_num, next_dir_num = process_epub(
            epub_path=epub_path,
            catalog_works=catalog_works,
            catalog_authors=catalog_authors,
            next_work_num=next_work_num,
            next_dir_num=next_dir_num,
            output_dir=args.output_dir,
            db_path=args.db_path,
            dry_run=args.dry_run,
        )
        all_reports.append(report)

    # Summary
    total_detected = sum(r.works_detected for r in all_reports)
    total_new = sum(r.works_new for r in all_reports)
    total_dup = sum(r.works_duplicate for r in all_reports)
    total_written = sum(r.works_written for r in all_reports)
    total_errors = sum(len(r.errors) for r in all_reports)

    logger.info(f"\n{'='*70}")
    logger.info("SUMMARY")
    logger.info(f"{'='*70}")
    logger.info(f"  EPUBs processed:  {len(all_reports)}")
    logger.info(f"  Works detected:   {total_detected}")
    logger.info(f"  New works:        {total_new}")
    logger.info(f"  Duplicates:       {total_dup}")
    if not args.dry_run:
        logger.info(f"  Files written:    {total_written}")
    logger.info(f"  Errors:           {total_errors}")

    for report in all_reports:
        if report.errors:
            logger.warning(f"  Errors in {report.epub_file[:50]}:")
            for err in report.errors:
                logger.warning(f"    - {err}")

    # Save report
    if args.report:
        report_data = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "dry_run": args.dry_run,
            "summary": {
                "epubs_processed": len(all_reports),
                "works_detected": total_detected,
                "works_new": total_new,
                "works_duplicate": total_dup,
                "works_written": total_written,
                "errors": total_errors,
            },
            "per_epub": [asdict(r) for r in all_reports],
        }
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        logger.info(f"\nReport saved to: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
