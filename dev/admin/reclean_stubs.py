#!/usr/bin/env python3
"""
Re-clean 32 Stub Files

These cleaned files have empty body.chapters despite their raw sources having real content.
This script re-runs the cleaning pipeline (stages 3-6) on just these 32 works.

Usage:
    python dev/admin/reclean_stubs.py                  # Re-clean all 32 stubs
    python dev/admin/reclean_stubs.py --verify          # Verify stubs have chapters
    python dev/admin/reclean_stubs.py --dry-run         # Show what would be done
    python dev/admin/reclean_stubs.py --limit 5         # Process first 5 only
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from datetime import datetime

# Resolve project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent / "iron_abacus_translator"
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# The 32 stub work IDs with empty body.chapters
STUB_WORK_IDS = [
    "D10O5", "D10P6", "D10U4", "D1130", "D14U3", "D14U4", "D1535", "D1539",
    "D1543", "D1549", "D16Q0", "D16R4", "D16S4", "D17B6", "D17F5", "D17G3",
    "D17G7", "D17G8", "D17H1", "D17H2", "D17H4", "D17K4", "D17L1", "D17P4",
    "D17P9", "D17Q7", "D17S5", "D17T0", "D17X2", "D259", "D260", "I09E2",
]

# Paths
RAW_DIR = Path.home() / "project_files" / "translation_project" / "work_individual_files"
OUTPUT_DIR = Path.home() / "project_files" / "translation_project" / "cleaned" / "COMPLETE_ALL_BOOKS"
CATALOG_PATH = Path.home() / "project_files" / "translation_project" / "db" / "works_translator.duckdb"


def find_raw_source(work_id: str) -> Path | None:
    """Find the raw JSON source file for a work ID."""
    for folder in sorted(RAW_DIR.iterdir()):
        if not folder.is_dir():
            continue
        for json_file in folder.glob(f"*{work_id}*.json"):
            # Skip summary files and non-source files
            if "summary" in json_file.name.lower():
                continue
            if "haodoo_page" in json_file.name.lower():
                continue
            return json_file
    return None


def find_cleaned_output(work_id: str) -> Path | None:
    """Find the existing cleaned output file for a work ID."""
    for folder in OUTPUT_DIR.iterdir():
        if not folder.is_dir():
            continue
        for json_file in folder.glob(f"*{work_id}*.json"):
            return json_file
    return None


def get_output_dir_for_work(work_id: str) -> Path | None:
    """Get the output directory (work_NNNN folder) for a work."""
    # Check if there's already a cleaned file — use its directory
    existing = find_cleaned_output(work_id)
    if existing:
        return existing.parent

    # Otherwise find from raw source
    raw = find_raw_source(work_id)
    if raw:
        folder_name = raw.parent.name  # e.g. work_0015
        out_dir = OUTPUT_DIR / folder_name
        return out_dir
    return None


def check_has_chapters(path: Path) -> tuple[bool, int]:
    """Check if a cleaned JSON file has non-empty chapters. Returns (has_chapters, count)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        return bool(chapters), len(chapters)
    except Exception:
        return False, 0


def reclean_work(work_id: str, dry_run: bool = False) -> dict:
    """Re-clean a single work through stages 3-6."""
    from processors.json_cleaner import clean_book_json
    from utils.embedded_chapter_detector import detect_embedded_chapters
    from utils.fix_chapter_alignment import ChapterAlignmentFixer
    from utils.restructure_toc import TOCRestructurer

    result = {"work_id": work_id, "success": False, "chapters": 0, "error": None}

    # Find raw source
    raw_path = find_raw_source(work_id)
    if not raw_path:
        result["error"] = "Raw source not found"
        return result

    # Determine output
    out_dir = get_output_dir_for_work(work_id)
    if not out_dir:
        result["error"] = "Cannot determine output directory"
        return result

    result["raw_path"] = str(raw_path)
    result["output_dir"] = str(out_dir)

    if dry_run:
        logger.info(f"  [DRY RUN] Would re-clean {work_id}: {raw_path.name} -> {out_dir}")
        result["success"] = True
        return result

    try:
        # Stage 3: JSON cleaning (takes file path, handles loading internally)
        cleaned = clean_book_json(
            str(raw_path),
            language_hint="zh-Hant",
            catalog_path=str(CATALOG_PATH) if CATALOG_PATH.exists() else None,
            directory_name=raw_path.parent.name,
        )

        # Stage 4: Embedded chapter detection
        try:
            detect_embedded_chapters(cleaned)
        except Exception as e:
            logger.debug(f"  Embedded chapter detection: {e}")

        # Stage 5: Chapter alignment fix
        try:
            fixer = ChapterAlignmentFixer()
            fixer.fix(cleaned)
        except Exception as e:
            logger.debug(f"  Alignment fix: {e}")

        # Stage 6: TOC restructuring
        try:
            restructurer = TOCRestructurer()
            restructurer.restructure(cleaned)
        except Exception as e:
            logger.debug(f"  TOC restructure: {e}")

        # Verify we have chapters now
        chapters = cleaned.get("structure", {}).get("body", {}).get("chapters", [])
        result["chapters"] = len(chapters)

        if not chapters:
            # Check front_matter for novella content
            front = cleaned.get("structure", {}).get("front_matter", {})
            content_blocks = []
            for section in front.get("sections", []):
                content_blocks.extend(section.get("content_blocks", []))
            if not content_blocks:
                intro = front.get("introduction", {})
                content_blocks.extend(intro.get("content_blocks", []))

            if content_blocks:
                # Novella — wrap in synthetic chapter
                title = cleaned.get("meta", {}).get("title", work_id)
                cleaned.setdefault("structure", {}).setdefault("body", {})["chapters"] = [{
                    "chapter_number": 1,
                    "title": title,
                    "content_blocks": content_blocks,
                }]
                result["chapters"] = 1
                result["novella"] = True
                logger.info(f"  {work_id}: Novella — synthesized 1 chapter from {len(content_blocks)} blocks")
            else:
                result["error"] = "No chapters or content found after cleaning"
                return result

        # Verify blocks have IDs
        for ch in cleaned.get("structure", {}).get("body", {}).get("chapters", []):
            for i, block in enumerate(ch.get("content_blocks", [])):
                if "id" not in block:
                    block["id"] = f"block_{i:04d}"

        # Write output
        out_dir.mkdir(parents=True, exist_ok=True)
        output_filename = f"cleaned_{raw_path.stem}.json"
        output_path = out_dir / output_filename

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, ensure_ascii=False, indent=2)

        result["success"] = True
        result["output_path"] = str(output_path)
        total_blocks = sum(len(ch.get("content_blocks", [])) for ch in chapters)
        logger.info(f"  {work_id}: {result['chapters']} chapters, {total_blocks} blocks -> {output_path.name}")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"  {work_id}: FAILED — {e}")

    return result


def verify_stubs(work_ids: list[str]) -> dict:
    """Verify which stubs have chapters and which are still empty."""
    results = {"has_chapters": [], "empty": [], "not_found": []}

    for work_id in work_ids:
        cleaned_path = find_cleaned_output(work_id)
        if not cleaned_path:
            results["not_found"].append(work_id)
            continue

        has_ch, count = check_has_chapters(cleaned_path)
        if has_ch:
            results["has_chapters"].append((work_id, count))
        else:
            results["empty"].append(work_id)

    return results


def main():
    parser = argparse.ArgumentParser(description="Re-clean 32 stub files with empty chapters")
    parser.add_argument("--verify", action="store_true", help="Only verify stub status")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("--limit", type=int, help="Process only first N stubs")
    parser.add_argument("--work-id", help="Process a single work ID")
    args = parser.parse_args()

    work_ids = STUB_WORK_IDS
    if args.work_id:
        work_ids = [args.work_id]
    if args.limit:
        work_ids = work_ids[:args.limit]

    if args.verify:
        print(f"\nVerifying {len(work_ids)} stubs...\n")
        results = verify_stubs(work_ids)

        if results["has_chapters"]:
            print(f"  Has chapters ({len(results['has_chapters'])}):")
            for wid, count in results["has_chapters"]:
                print(f"    {wid}: {count} chapters")

        if results["empty"]:
            print(f"\n  Empty ({len(results['empty'])}):")
            for wid in results["empty"]:
                print(f"    {wid}")

        if results["not_found"]:
            print(f"\n  Not found ({len(results['not_found'])}):")
            for wid in results["not_found"]:
                print(f"    {wid}")

        total = len(results["has_chapters"])
        print(f"\n  Summary: {total}/{len(work_ids)} have chapters")
        return 0

    # Re-clean
    print(f"\nRe-cleaning {len(work_ids)} stubs...\n")
    start_time = datetime.now()

    succeeded = 0
    failed = 0
    results = []

    for work_id in work_ids:
        logger.info(f"Processing {work_id}...")
        result = reclean_work(work_id, dry_run=args.dry_run)
        results.append(result)
        if result["success"]:
            succeeded += 1
        else:
            failed += 1
            logger.error(f"  FAILED: {result.get('error', 'unknown')}")

    duration = (datetime.now() - start_time).total_seconds()

    # Summary
    print(f"\n{'='*60}")
    print(f"  Re-clean complete: {succeeded}/{len(work_ids)} succeeded, {failed} failed")
    print(f"  Duration: {duration:.1f}s")
    print(f"{'='*60}")

    if failed:
        print("\n  Failed works:")
        for r in results:
            if not r["success"]:
                print(f"    {r['work_id']}: {r.get('error', 'unknown')}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
