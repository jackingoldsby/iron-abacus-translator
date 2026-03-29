#!/usr/bin/env python3
"""
Sync enriched fields from DuckDB back to status.json files in the library.
"""

import json
import logging

import duckdb

from azure_register.config.defaults import LIBRARY_ROOT

logger = logging.getLogger(__name__)


def sync_to_status_json(con: duckdb.DuckDBPyConnection):
    """Sync enriched fields from DuckDB back to status.json files."""
    works = con.execute("""
        SELECT work_number, title_english, author_english, publication_year,
               publication_note, setting_period, summary, category_english,
               enriched_at, library_path
        FROM works
        WHERE enriched_at IS NOT NULL AND library_path IS NOT NULL
    """).fetchall()
    columns = [desc[0] for desc in con.description]

    updated = 0
    for row in works:
        w = dict(zip(columns, row))
        lib_path = LIBRARY_ROOT / w["library_path"] / "status.json"
        if not lib_path.exists():
            continue

        try:
            with open(lib_path, "r", encoding="utf-8") as f:
                status = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        changed = False
        sync_fields = {
            "title_english": w["title_english"],
            "author_english": w["author_english"],
            "publication_year": w["publication_year"],
            "publication_note": w["publication_note"],
            "setting_period": w["setting_period"],
            "description": w["summary"],
            "genre_tags": w["category_english"].split(", ") if w.get("category_english") else None,
            "enriched_at": w["enriched_at"].isoformat() if w.get("enriched_at") else None,
        }

        for field, val in sync_fields.items():
            if val is not None and status.get(field) != val:
                status[field] = val
                changed = True

        if changed:
            with open(lib_path, "w", encoding="utf-8") as f:
                json.dump(status, f, ensure_ascii=False, indent=2)
                f.write("\n")
            updated += 1

    logger.info(f"Synced {updated} status.json files")
