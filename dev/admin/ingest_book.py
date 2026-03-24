#!/usr/bin/env python3
"""
Inbox Processor

Scans the inbox/ directory for new raw book files, looks up their catalog
entry, creates the library skeleton, and moves raw files into place.

Usage:
    python scripts/ingest_book.py              # Process all files in inbox/
    python scripts/ingest_book.py --dry-run     # Preview only
"""

import sys
import re
import json
import shutil
import argparse
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "iron_abacus_translator"))

from utils.library_path_resolver import (
    resolve_work_info,
    create_work_skeleton,
    build_status_json,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def extract_work_number(filename: str) -> str | None:
    """
    Extract work number from a filename.

    Patterns:
        D438_白髮魔女傳_梁羽生.json  -> D438
        D55a_射鵰英雄傳一_金庸.json  -> D55
        FSYY_封神演義_許仲琳.json    -> FSYY
        cleaned_D438_白髮... .json   -> D438
    """
    stem = Path(filename).stem

    # Strip common prefixes
    for prefix in ["cleaned_", "translated_", "translated_cleaned_"]:
        if stem.startswith(prefix):
            stem = stem[len(prefix):]

    # Match work_number pattern: letters+digits, optionally followed by volume letter
    m = re.match(r"([A-Z]+\d+[A-Z]*\d*)", stem)
    if m:
        wn = m.group(1)
        # Strip trailing volume letter (a-z) if preceded by digit
        if len(wn) > 1 and wn[-1].islower() and wn[-2].isdigit():
            return wn[:-1]
        return wn

    # Try FSYY-style (all-alpha codes)
    m = re.match(r"([A-Z]{3,})", stem)
    if m:
        return m.group(1)

    return None


def process_inbox(data_root: Path, catalog_path: Path, dry_run: bool = False) -> dict:
    """Process all files in inbox/."""
    inbox_dir = data_root / "inbox"
    library_root = data_root / "library"

    if not inbox_dir.exists():
        if dry_run:
            logger.info(f"Inbox dir does not exist: {inbox_dir}")
        else:
            inbox_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created inbox: {inbox_dir}")
        return {"ingested": 0, "skipped": 0, "errors": []}

    stats = {"ingested": 0, "skipped": 0, "errors": []}

    for f in sorted(inbox_dir.glob("*.json")):
        work_number = extract_work_number(f.name)
        if not work_number:
            logger.warning(f"Cannot extract work number from: {f.name}")
            stats["errors"].append(f"Unknown work number: {f.name}")
            continue

        info = resolve_work_info(work_number, catalog_path)
        if not info:
            logger.warning(f"Work {work_number} not found in catalog")
            stats["errors"].append(f"{work_number}: not in catalog")
            continue

        # Create skeleton
        work_path = library_root / info.relative_path
        if dry_run:
            logger.info(f"Would create skeleton: library/{info.relative_path}/")
        else:
            create_work_skeleton(work_number, library_root, catalog_path)

        # Determine volume
        vol = None
        if info.volumes:
            stem = f.stem
            for v in info.volumes:
                if f"{work_number}{v}" in stem:
                    vol = v
                    break

        # Move raw file
        if vol:
            dst = work_path / f"vol_{vol}" / "raw" / f"{work_number}{vol}.json"
        else:
            dst = work_path / "raw" / f"{work_number}.json"

        if dry_run:
            logger.info(f"Would move: {f.name} -> {dst}")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dst))
            logger.info(f"Ingested: {f.name} -> library/{info.relative_path}/")

        # Write status.json if it doesn't exist
        status_path = work_path / "status.json"
        if not status_path.exists():
            status = build_status_json(work_number, catalog_path)
            if status and not dry_run:
                with open(status_path, "w", encoding="utf-8") as sf:
                    json.dump(status, sf, indent=2, ensure_ascii=False)

        stats["ingested"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Ingest books from inbox/")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    from utils.environment_config import get_or_create_config
    config = get_or_create_config()

    stats = process_inbox(config.data_root, config.catalog_path, dry_run=args.dry_run)

    print(f"\nIngested: {stats['ingested']}")
    print(f"Skipped:  {stats['skipped']}")
    if stats["errors"]:
        print(f"Errors:   {len(stats['errors'])}")
        for e in stats["errors"]:
            print(f"  - {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
