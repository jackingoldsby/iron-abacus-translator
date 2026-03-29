#!/usr/bin/env python3
"""
CsvEnricher — CSV-to-DB import.

Reads a works CSV and updates the catalog database with English metadata.
No LLM usage.
"""

import csv
import logging
from pathlib import Path
from typing import Optional

import duckdb

from azure_register.enrichers.base import BaseEnricher

logger = logging.getLogger(__name__)


class CsvEnricher(BaseEnricher):
    """Import metadata from CSV into the works catalog."""

    def load(self, csv_path: str, dry_run: bool = False):
        """Read CSV, match by directory_number, update DB.

        Args:
            csv_path: Path to works.csv file.
            dry_run: If True, show what would change without writing.
        """
        csv_file = Path(csv_path)
        if not csv_file.exists():
            print(f"CSV not found: {csv_file}")
            return

        con = self.connect()
        try:
            self.migrate_schema(con)
            csv_data = self._load_csv(csv_file)

            if dry_run:
                print(f"[DRY RUN] Would update works from {len(csv_data)} CSV entries")
                return

            self._enrich(con, csv_data)
            self._verify(con)
        finally:
            con.close()

    @staticmethod
    def _load_csv(csv_path: Path) -> dict[str, dict]:
        """Load CSV data keyed by directory number (e.g. '0001')."""
        data: dict[str, dict] = {}
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                work_key = row["work_key"]  # e.g. "work_0001" or "wuxia_0001"
                dir_num = work_key.replace("work_", "").replace("wuxia_", "")
                data[dir_num] = {
                    "author_english": row.get("Initial_Author_English", ""),
                    "title_english": row.get("Initial_Title_English", ""),
                    "category_english": row.get("Category_English", ""),
                    "summary": row.get("Summary", ""),
                    "author_chinese": row.get("author_chinese", ""),
                    "title_chinese": row.get("title_chinese", ""),
                    "work_link": row.get("work_link", ""),
                }
        print(f"Loaded {len(data)} entries from CSV")
        return data

    def _enrich(self, con: duckdb.DuckDBPyConnection, csv_data: dict[str, dict]):
        """Update database with CSV data based on directory_number."""
        rows = con.execute("SELECT work_id, directory_number FROM works").fetchall()

        updated = 0
        missing = 0

        for work_id, dir_number in rows:
            if dir_number in csv_data:
                d = csv_data[dir_number]
                con.execute(
                    """
                    UPDATE works
                    SET author_english = ?,
                        title_english = ?,
                        category_english = ?,
                        summary = ?,
                        author_chinese = ?,
                        title_chinese = ?,
                        work_link = ?
                    WHERE work_id = ?
                    """,
                    (
                        d["author_english"], d["title_english"],
                        d["category_english"], d["summary"],
                        d["author_chinese"], d["title_chinese"],
                        d["work_link"], work_id,
                    ),
                )
                updated += 1
            else:
                missing += 1

        print(f"\nUpdated {updated} works")
        if missing:
            print(f"{missing} works missing CSV data")

    @staticmethod
    def _verify(con: duckdb.DuckDBPyConnection):
        """Show sample enriched data."""
        print("\nSample enriched works:")
        rows = con.execute("""
            SELECT work_number, title_author, author_english, title_english, category_english
            FROM works
            WHERE author_english IS NOT NULL AND author_english != ''
            ORDER BY directory_number
            LIMIT 5
        """).fetchall()

        for work_num, title_auth, auth_en, title_en, cat_en in rows:
            print(f"  {work_num}: {auth_en} - {title_en}")
            if cat_en:
                print(f"    genre: {cat_en}")
