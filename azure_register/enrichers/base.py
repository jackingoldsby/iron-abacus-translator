#!/usr/bin/env python3
"""
BaseEnricher — shared DB, batching, diff, change computation.

Concrete enrichers (LibraryEnricher, ReaderEnricher) inherit from this.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Callable, Optional

import duckdb

from azure_register.schema.migrations import ensure_schema
from azure_register.utils.db import connect_catalog

logger = logging.getLogger(__name__)


class BaseEnricher:
    """Base class for all catalog enrichers."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        workers: int = 50,
        batch_size: int = 10,
        dry_run: bool = False,
        diff: bool = False,
    ):
        self.db_path = db_path
        self.workers = workers
        self.batch_size = batch_size
        self.dry_run = dry_run
        self.diff = diff

        # Stats
        self.total_work_updates = 0
        self.total_author_updates = 0
        self.total_unchanged = 0

    def connect(self) -> duckdb.DuckDBPyConnection:
        """Connect to the catalog database."""
        return connect_catalog(self.db_path)

    def migrate_schema(self, con: duckdb.DuckDBPyConnection):
        """Run all schema migrations."""
        ensure_schema(con)

    # --- DB queries ---

    def fetch_works(
        self,
        con: duckdb.DuckDBPyConnection,
        columns: list[str],
        author_filter: Optional[str] = None,
        unenriched_only: bool = False,
        unenriched_column: str = "enriched_at",
        limit: Optional[int] = None,
    ) -> list[dict]:
        """Query works table with optional filtering."""
        col_str = ", ".join(f"w.{c}" for c in columns if not c.startswith("a."))
        # Add any author-prefixed columns
        author_cols = [c for c in columns if c.startswith("a.")]
        if author_cols:
            col_str += ", " + ", ".join(author_cols)

        query = f"""
            SELECT {col_str}
            FROM works w
            LEFT JOIN authors a ON w.author_chinese = a.name_chinese
            WHERE 1=1
        """
        params: list[Any] = []

        if author_filter:
            query += " AND LOWER(w.author_english) LIKE ?"
            params.append(f"%{author_filter.lower()}%")

        if unenriched_only:
            query += f" AND w.{unenriched_column} IS NULL"

        query += " ORDER BY w.work_number"

        if limit:
            query += f" LIMIT {limit}"

        rows = con.execute(query, params).fetchall()
        col_names = [desc[0] for desc in con.description]
        return [dict(zip(col_names, row)) for row in rows]

    def fetch_authors(self, con: duckdb.DuckDBPyConnection, columns: list[str]) -> dict[str, dict]:
        """Load all authors keyed by name_chinese."""
        col_str = ", ".join(columns)
        rows = con.execute(f"SELECT {col_str} FROM authors").fetchall()
        col_names = [desc[0] for desc in con.description]
        return {row[0]: dict(zip(col_names, row)) for row in rows}

    # --- DB writes ---

    def apply_work_changes(
        self,
        con: duckdb.DuckDBPyConnection,
        work_number: str,
        changes: dict[str, dict],
        timestamp_column: str = "enriched_at",
    ):
        """UPDATE works SET ... for changed fields."""
        if not changes:
            return

        sets = []
        params: list[Any] = []
        for field_name, vals in changes.items():
            if field_name.endswith("_suggestion"):
                continue
            sets.append(f"{field_name} = ?")
            params.append(vals["new"])

        sets.append(f"{timestamp_column} = ?")
        params.append(datetime.now())

        if not sets:
            con.execute(
                f"UPDATE works SET {timestamp_column} = ? WHERE work_number = ?",
                [datetime.now(), work_number],
            )
            return

        params.append(work_number)
        sql = f"UPDATE works SET {', '.join(sets)} WHERE work_number = ?"
        con.execute(sql, params)

    def apply_author_changes(
        self,
        con: duckdb.DuckDBPyConnection,
        name_chinese: str,
        changes: dict[str, dict],
    ):
        """UPDATE authors SET ... for changed fields."""
        if not changes:
            return

        sets = []
        params: list[Any] = []
        for field_name, vals in changes.items():
            sets.append(f"{field_name} = ?")
            params.append(vals["new"])

        params.append(name_chinese)
        sql = f"UPDATE authors SET {', '.join(sets)} WHERE name_chinese = ?"
        con.execute(sql, params)

    def mark_enriched(
        self,
        con: duckdb.DuckDBPyConnection,
        work_number: str,
        timestamp_column: str = "enriched_at",
    ):
        """Mark a work as enriched even if no fields changed."""
        con.execute(
            f"UPDATE works SET {timestamp_column} = ? WHERE work_number = ?",
            [datetime.now(), work_number],
        )

    # --- Batching ---

    def make_batches(self, items: list) -> list[list]:
        """Split items into batch_size chunks."""
        return [
            items[i : i + self.batch_size]
            for i in range(0, len(items), self.batch_size)
        ]

    def run_parallel(
        self,
        batches: list[list],
        fetch_fn: Callable[[tuple[int, list]], tuple[int, list, Optional[dict]]],
    ) -> list[tuple[int, list, Optional[dict]]]:
        """Run fetch_fn on batches using ThreadPoolExecutor.

        Args:
            batches: List of work batches.
            fetch_fn: Callable taking (batch_num, batch) returning (batch_num, batch, result).

        Returns:
            List of (batch_num, batch, result) tuples.
        """
        results = []
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {
                pool.submit(fetch_fn, (i, b)): i
                for i, b in enumerate(batches, 1)
            }
            for future in as_completed(futures):
                results.append(future.result())
        return results

    # --- Change computation ---

    @staticmethod
    def compute_changes(
        current: dict, enrichment: dict, fields: list[str]
    ) -> dict[str, dict]:
        """Only fill empty fields. Returns {field: {old, new}}."""
        changes = {}
        for field_name in fields:
            new_val = enrichment.get(field_name)
            if new_val is None:
                continue
            old_val = current.get(field_name)
            if not old_val and new_val:
                changes[field_name] = {"old": old_val, "new": new_val}
        return changes

    # --- Display ---

    @staticmethod
    def show_diff(label: str, changes: dict[str, dict]):
        """Display field-level diff for a single entity."""
        if not changes:
            return
        print(f"\n  {label}:")
        for field_name, vals in changes.items():
            old = vals["old"] if vals["old"] is not None else "(none)"
            new = vals["new"]
            suffix = " [SUGGESTION ONLY]" if field_name.endswith("_suggestion") else ""
            print(f"    {field_name}{suffix}:")
            print(f"      - {old}")
            print(f"      + {new}")

    def print_summary(self, label: str, total_processed: int):
        """Print enrichment summary."""
        print(f"\n{'=' * 60}")
        print(f"  {label} complete")
        print(f"  Works updated:    {self.total_work_updates}")
        print(f"  Works unchanged:  {self.total_unchanged}")
        print(f"  Authors updated:  {self.total_author_updates}")
        print(f"  Total processed:  {total_processed}")
        print(f"{'=' * 60}")
