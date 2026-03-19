#!/usr/bin/env python3
"""
Storage Migration Script

Migrates translation project files from the old flat layout to the new
author/series/work library structure.

Old layout:
    wuxia_individual_files/wuxia_NNNN/   (raw)
    cleaned/COMPLETE_ALL_BOOKS/wuxia_NNNN/  (cleaned)
    wip/stage_N_*/filename.json          (WIP by stage)
    translated/translated_*.json         (final output)
    logs/filename_stage_N_*.json         (logs)

New layout:
    library/Author/Series/NN_Title/[vol_X/]{raw,cleaned,translation}/
    logs/WORK_NUMBER/stage_N_*.json

Usage:
    python scripts/migrate_storage.py --dry-run    # Preview only
    python scripts/migrate_storage.py              # Execute migration
    python scripts/migrate_storage.py --work D438  # Migrate single work
"""

import sys
import json
import shutil
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.library_path_resolver import (
    resolve_work_info,
    create_work_skeleton,
    build_status_json,
    WorkLibraryInfo,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class StorageMigrator:
    """Migrates files from old layout to library/ structure."""

    def __init__(
        self,
        data_root: Path,
        catalog_path: Path,
        dry_run: bool = False,
    ):
        self.data_root = data_root
        self.catalog_path = catalog_path
        self.dry_run = dry_run
        self.library_root = data_root / "library"

        # Old dirs
        self.old_raw_dir = data_root / "wuxia_individual_files"
        self.old_cleaned_dir = data_root / "cleaned" / "COMPLETE_ALL_BOOKS"
        self.old_wip_dir = data_root / "wip"
        self.old_translated_dir = data_root / "translated"
        self.old_log_dir = data_root / "logs"
        self.new_log_dir = data_root / "logs"  # logs stay centralized

        # Stats
        self.stats = {
            "works_resolved": 0,
            "works_failed": 0,
            "raw_copied": 0,
            "cleaned_copied": 0,
            "wip_copied": 0,
            "translated_copied": 0,
            "logs_copied": 0,
            "epubs_copied": 0,
            "status_written": 0,
            "skipped_exists": 0,
            "errors": [],
        }

    def _copy_file(self, src: Path, dst: Path, label: str = "") -> bool:
        """Copy a file, creating parent dirs. Returns True if copied."""
        if not src.exists():
            return False

        if dst.exists():
            self.stats["skipped_exists"] += 1
            logger.debug(f"  Skip (exists): {dst}")
            return False

        if self.dry_run:
            logger.info(f"  Would copy {label}: {src.name} -> {dst}")
            return True

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        logger.debug(f"  Copied {label}: {src.name} -> {dst}")
        return True

    def _matches_work_number(self, filename: str, work_number: str) -> bool:
        """Check if a filename actually matches work_number (not just a prefix).

        D55 should match D55a_..., D55_... but NOT D552_...
        """
        stem = Path(filename).stem
        # Find work_number in the stem
        idx = stem.find(work_number)
        if idx < 0:
            return False
        after = idx + len(work_number)
        if after >= len(stem):
            return True  # work_number is at the end
        next_char = stem[after]
        # Valid: volume letter (a-z), underscore, period, dash
        # Invalid: digit (would mean a different work number like D552 vs D55)
        return not next_char.isdigit()

    def _find_raw_files(self, work_number: str, info: WorkLibraryInfo) -> List[Tuple[Path, str]]:
        """Find raw source files. Returns list of (source_path, volume_or_empty)."""
        import duckdb
        conn = duckdb.connect(str(self.catalog_path), read_only=True)
        rows = conn.execute("""
            SELECT wf.filename, wf.directory_name, wf.volume
            FROM works w
            JOIN work_files wf ON w.work_id = wf.work_id
            WHERE w.work_number = ?
        """, [work_number]).fetchall()
        conn.close()

        results = []
        seen = set()
        for filename, dir_name, volume in rows:
            raw_path = self.old_raw_dir / dir_name / filename
            if raw_path.exists() and raw_path not in seen:
                results.append((raw_path, volume or ""))
                seen.add(raw_path)
            else:
                alt = self.old_raw_dir / dir_name
                if alt.is_dir():
                    for f in alt.glob("*.json"):
                        if self._matches_work_number(f.name, work_number) and f not in seen:
                            results.append((f, volume or ""))
                            seen.add(f)
        return results

    def _find_cleaned_files(self, work_number: str, info: WorkLibraryInfo) -> List[Tuple[Path, str]]:
        """Find cleaned files. Returns list of (source_path, volume_or_empty)."""
        import duckdb
        conn = duckdb.connect(str(self.catalog_path), read_only=True)
        rows = conn.execute("""
            SELECT DISTINCT wf.directory_name, wf.volume
            FROM works w
            JOIN work_files wf ON w.work_id = wf.work_id
            WHERE w.work_number = ?
        """, [work_number]).fetchall()
        conn.close()

        results = []
        seen = set()
        checked_dirs = set()

        for dir_name, volume in rows:
            cleaned_dir = self.old_cleaned_dir / dir_name
            if cleaned_dir.is_dir() and dir_name not in checked_dirs:
                checked_dirs.add(dir_name)
                for f in cleaned_dir.glob("*.json"):
                    if self._matches_work_number(f.name, work_number) and f not in seen:
                        # Determine volume from filename
                        file_vol = self._determine_volume_for_file(f, info) or ""
                        results.append((f, file_vol))
                        seen.add(f)

        # Also check other dirs (fengshen-style) for non-wuxia works
        if self.old_cleaned_dir.exists():
            for special_dir in self.old_cleaned_dir.iterdir():
                if not special_dir.is_dir() or special_dir.name in checked_dirs:
                    continue
                for f in special_dir.glob("*.json"):
                    if self._matches_work_number(f.name, work_number) and f not in seen:
                        file_vol = self._determine_volume_for_file(f, info) or ""
                        results.append((f, file_vol))
                        seen.add(f)

        return results

    def _find_wip_files(self, work_number: str) -> List[Tuple[Path, str]]:
        """Find WIP files across stage dirs. Returns (path, stage_dir_name)."""
        results = []
        if not self.old_wip_dir.exists():
            return results

        for stage_dir in sorted(self.old_wip_dir.iterdir()):
            if not stage_dir.is_dir():
                continue
            if not stage_dir.name.startswith("stage_"):
                continue
            for f in stage_dir.glob("*.json"):
                if work_number in f.name:
                    results.append((f, stage_dir.name))
        return results

    def _find_translated_files(self, work_number: str) -> List[Path]:
        """Find translated output files."""
        results = []
        if not self.old_translated_dir.exists():
            return results
        for f in self.old_translated_dir.glob("*.json"):
            if work_number in f.name:
                results.append(f)
        return results

    def _find_epub_files(self, work_number: str, info: WorkLibraryInfo) -> List[Path]:
        """Find EPUB files."""
        results = []
        if not self.old_translated_dir.exists():
            return results
        for f in self.old_translated_dir.glob("*.epub"):
            if work_number in f.name:
                results.append(f)
        # Also check by title
        title_lower = info.title_english.lower().replace(" ", "")
        for f in self.old_translated_dir.glob("*.epub"):
            name_lower = f.stem.lower().replace(" ", "").replace("_", "").replace("-", "")
            if title_lower.replace(" ", "") in name_lower and f not in results:
                results.append(f)
        return results

    def _find_log_files(self, work_number: str) -> List[Path]:
        """Find log files for this work."""
        results = []
        if not self.old_log_dir.exists():
            return results
        for f in self.old_log_dir.glob("*.json"):
            if work_number in f.name:
                results.append(f)
        for f in self.old_log_dir.glob("*.log"):
            if work_number in f.name:
                results.append(f)
        return results

    def _determine_volume_for_file(self, filepath: Path, info: WorkLibraryInfo) -> Optional[str]:
        """Determine which volume a file belongs to based on filename."""
        if not info.volumes:
            return None

        name = filepath.stem
        work_num = info.work_number
        # Pattern: D55a_... or D55b_... — volume letter right after work number
        for vol in info.volumes:
            if f"{work_num}{vol}" in name:
                return vol
        return None

    def _detect_completed_stages(self, work_number: str) -> List[int]:
        """Detect which pipeline stages have been completed."""
        stages = []
        wip_files = self._find_wip_files(work_number)
        for _, stage_dir_name in wip_files:
            # Extract stage number from "stage_N_name"
            import re
            m = re.match(r"stage_(\d+)_", stage_dir_name)
            if m:
                stages.append(int(m.group(1)))
        return sorted(set(stages))

    def migrate_work(self, work_number: str) -> bool:
        """Migrate a single work. Returns True on success."""
        info = resolve_work_info(work_number, self.catalog_path)
        if not info:
            logger.warning(f"Could not resolve {work_number}")
            self.stats["works_failed"] += 1
            self.stats["errors"].append(f"{work_number}: not found in catalog")
            return False

        work_path = self.library_root / info.relative_path
        logger.info(f"Migrating {work_number}: library/{info.relative_path}/")

        # Create skeleton
        create_work_skeleton(
            work_number, self.library_root, self.catalog_path,
            dry_run=self.dry_run,
        )

        # --- Copy raw files ---
        raw_files = self._find_raw_files(work_number, info)
        for src, volume in raw_files:
            vol = self._determine_volume_for_file(src, info)
            if vol:
                dst = work_path / f"vol_{vol}" / "raw" / f"{work_number}{vol}.json"
            else:
                dst = work_path / "raw" / f"{work_number}.json"
            if self._copy_file(src, dst, "raw"):
                self.stats["raw_copied"] += 1

        # --- Copy cleaned files ---
        cleaned_files = self._find_cleaned_files(work_number, info)
        for src, volume in cleaned_files:
            vol = self._determine_volume_for_file(src, info)
            if vol:
                dst = work_path / f"vol_{vol}" / "cleaned" / f"{work_number}{vol}.json"
            else:
                dst = work_path / "cleaned" / f"{work_number}.json"
            if self._copy_file(src, dst, "cleaned"):
                self.stats["cleaned_copied"] += 1

        # --- Copy WIP files ---
        wip_files = self._find_wip_files(work_number)
        for src, stage_dir_name in wip_files:
            vol = self._determine_volume_for_file(src, info)
            # stage_dir_name like "stage_1_body" -> extract just "stage_1_body.json"
            wip_filename = f"{stage_dir_name}.json"
            if vol:
                dst = work_path / f"vol_{vol}" / "translation" / "wip" / wip_filename
            else:
                dst = work_path / "translation" / "wip" / wip_filename
            if self._copy_file(src, dst, "wip"):
                self.stats["wip_copied"] += 1

        # --- Copy translated files ---
        translated_files = self._find_translated_files(work_number)
        for src in translated_files:
            vol = self._determine_volume_for_file(src, info)
            if vol:
                dst = work_path / f"vol_{vol}" / "translation" / f"{work_number}{vol}.json"
            else:
                dst = work_path / "translation" / f"{work_number}.json"
            if self._copy_file(src, dst, "translated"):
                self.stats["translated_copied"] += 1

        # --- Copy EPUB files ---
        epub_files = self._find_epub_files(work_number, info)
        for src in epub_files:
            dst = work_path / "epub" / src.name
            if self._copy_file(src, dst, "epub"):
                self.stats["epubs_copied"] += 1

        # --- Copy log files to centralized logs/WORK_NUMBER/ ---
        log_files = self._find_log_files(work_number)
        for src in log_files:
            dst = self.new_log_dir / work_number / src.name
            if self._copy_file(src, dst, "log"):
                self.stats["logs_copied"] += 1

        # --- Write status.json ---
        stages_completed = self._detect_completed_stages(work_number)
        has_epub = len(epub_files) > 0
        status = build_status_json(
            work_number, self.catalog_path,
            stages_completed=stages_completed,
            epub_generated=has_epub,
        )
        if status:
            status["last_run"] = datetime.now().isoformat()
            status_path = work_path / "status.json"
            if not status_path.exists():
                if self.dry_run:
                    logger.info(f"  Would write: {status_path}")
                else:
                    status_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(status_path, "w", encoding="utf-8") as f:
                        json.dump(status, f, indent=2, ensure_ascii=False)
                self.stats["status_written"] += 1

        self.stats["works_resolved"] += 1
        return True

    def migrate_all(self, limit: Optional[int] = None) -> Dict:
        """Migrate all works from the catalog."""
        import duckdb

        conn = duckdb.connect(str(self.catalog_path), read_only=True)
        work_numbers = [r[0] for r in conn.execute(
            "SELECT work_number FROM works ORDER BY work_number"
        ).fetchall()]
        conn.close()

        if limit:
            work_numbers = work_numbers[:limit]

        logger.info(f"Migrating {len(work_numbers)} works...")
        logger.info(f"Library root: {self.library_root}")
        logger.info(f"Dry run: {self.dry_run}")
        print()

        for i, wn in enumerate(work_numbers, 1):
            if i % 50 == 0:
                logger.info(f"Progress: {i}/{len(work_numbers)}")
            self.migrate_work(wn)

        return self.stats

    def update_duckdb_library_paths(self):
        """Add library_path column to works table and populate it."""
        import duckdb

        conn = duckdb.connect(str(self.catalog_path))
        try:
            # Check if column exists
            cols = conn.execute(
                "SELECT column_name FROM duckdb_columns() WHERE table_name = 'works'"
            ).fetchall()
            col_names = [c[0] for c in cols]

            if "library_path" not in col_names:
                if self.dry_run:
                    logger.info("Would add library_path column to works table")
                else:
                    conn.execute("ALTER TABLE works ADD COLUMN library_path VARCHAR")
                    logger.info("Added library_path column to works table")

            # Populate using a single connection — query all needed data first
            rows = conn.execute("""
                SELECT
                    w.work_number,
                    w.title_english,
                    w.author_english,
                    s.name_english AS series_name,
                    ws.order_in_series
                FROM works w
                LEFT JOIN work_series ws ON w.work_id = ws.work_id
                LEFT JOIN series s ON ws.series_id = s.series_id
            """).fetchall()

            updated = 0
            for wn, title, author, series, order in rows:
                from utils.library_path_resolver import sanitize_dirname
                author_dir = sanitize_dirname(author or "Unknown_Author")
                title_dir = sanitize_dirname(title or wn)

                if series:
                    series_dir = sanitize_dirname(series)
                    work_dir = f"{order:02d}_{title_dir}" if order else title_dir
                    rel_path = f"{author_dir}/{series_dir}/{work_dir}"
                else:
                    rel_path = f"{author_dir}/_standalone/{title_dir}"

                if not self.dry_run:
                    conn.execute(
                        "UPDATE works SET library_path = ? WHERE work_number = ?",
                        [rel_path, wn],
                    )
                updated += 1

            if not self.dry_run:
                logger.info(f"Updated library_path for {updated}/{len(rows)} works")
            else:
                logger.info(f"Would update library_path for {updated}/{len(rows)} works")
        finally:
            conn.close()

    def archive_old_dirs(self):
        """Move old directories to _archive/ and create symlinks."""
        archive_root = self.data_root / "_archive"

        dirs_to_archive = [
            ("wuxia_individual_files", self.old_raw_dir),
            ("cleaned", self.data_root / "cleaned"),
            ("wip", self.old_wip_dir),
            ("translated", self.old_translated_dir),
            ("translation_data", self.data_root / "translation_data"),
        ]

        for name, src_dir in dirs_to_archive:
            if not src_dir.exists() or src_dir.is_symlink():
                continue

            dst = archive_root / name
            if self.dry_run:
                logger.info(f"Would move {src_dir} -> {dst}")
                logger.info(f"Would create symlink {src_dir} -> {dst}")
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src_dir), str(dst))
                src_dir.symlink_to(dst)
                logger.info(f"Archived: {name} -> _archive/{name} (+ symlink)")


def main():
    parser = argparse.ArgumentParser(description="Migrate storage to library layout")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview only, don't write files",
    )
    parser.add_argument(
        "--work", type=str, default=None,
        help="Migrate single work (e.g., D438)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limit to first N works",
    )
    parser.add_argument(
        "--update-db", action="store_true",
        help="Add library_path column to DuckDB and populate",
    )
    parser.add_argument(
        "--archive", action="store_true",
        help="Move old dirs to _archive/ and create symlinks",
    )
    parser.add_argument(
        "--data-root", type=str, default=None,
        help="Override data root path",
    )
    args = parser.parse_args()

    from utils.environment_config import get_or_create_config
    config = get_or_create_config()

    data_root = Path(args.data_root) if args.data_root else config.data_root
    catalog_path = config.catalog_path

    migrator = StorageMigrator(
        data_root=data_root,
        catalog_path=catalog_path,
        dry_run=args.dry_run,
    )

    if args.update_db:
        migrator.update_duckdb_library_paths()
        return 0

    if args.archive:
        migrator.archive_old_dirs()
        return 0

    if args.work:
        success = migrator.migrate_work(args.work)
        print(f"\nResult: {'OK' if success else 'FAILED'}")
        print(json.dumps(migrator.stats, indent=2))
        return 0 if success else 1

    stats = migrator.migrate_all(limit=args.limit)

    print(f"\n{'='*60}")
    print(f"MIGRATION {'(DRY RUN) ' if args.dry_run else ''}COMPLETE")
    print(f"{'='*60}")
    print(f"Works resolved:    {stats['works_resolved']}")
    print(f"Works failed:      {stats['works_failed']}")
    print(f"Raw files copied:  {stats['raw_copied']}")
    print(f"Cleaned copied:    {stats['cleaned_copied']}")
    print(f"WIP copied:        {stats['wip_copied']}")
    print(f"Translated copied: {stats['translated_copied']}")
    print(f"EPUBs copied:      {stats['epubs_copied']}")
    print(f"Logs copied:       {stats['logs_copied']}")
    print(f"Status files:      {stats['status_written']}")
    print(f"Skipped (exists):  {stats['skipped_exists']}")

    if stats["errors"]:
        print(f"\nErrors ({len(stats['errors'])}):")
        for e in stats["errors"][:20]:
            print(f"  - {e}")

    return 0 if stats["works_failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
