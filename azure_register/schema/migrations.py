#!/usr/bin/env python3
"""
Schema migrations for the works catalog.

All ALTER TABLE statements in one place, run idempotently.
"""

import logging

import duckdb

logger = logging.getLogger(__name__)

# Ordered list of all migrations. Each runs with IF NOT EXISTS so they're safe to re-run.
MIGRATIONS = [
    # --- Library enrichment (factual metadata) ---
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS setting_period VARCHAR",
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS publication_note VARCHAR",
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS enriched_at TIMESTAMP",
    "ALTER TABLE authors ADD COLUMN IF NOT EXISTS pen_name_origin VARCHAR",

    # --- Reader enrichment (subjective metadata) ---
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS rating_tier VARCHAR",
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS rating_note VARCHAR",
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS writing_style VARCHAR",
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS themes VARCHAR",
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS mood VARCHAR",
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS comparable_works VARCHAR",
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS wuxia_era VARCHAR",
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS reader_enriched_at TIMESTAMP",
    "ALTER TABLE authors ADD COLUMN IF NOT EXISTS writing_style VARCHAR",
    "ALTER TABLE authors ADD COLUMN IF NOT EXISTS best_known_for VARCHAR",

    # --- CSV enrichment (basic metadata columns) ---
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS author_english VARCHAR",
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS title_english VARCHAR",
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS category_english VARCHAR",
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS summary VARCHAR",
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS author_chinese VARCHAR",
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS title_chinese VARCHAR",
    "ALTER TABLE works ADD COLUMN IF NOT EXISTS work_link VARCHAR",
]


def ensure_schema(con: duckdb.DuckDBPyConnection):
    """Run all migrations idempotently."""
    for sql in MIGRATIONS:
        try:
            con.execute(sql)
        except duckdb.CatalogException:
            # Column already exists (older DuckDB without IF NOT EXISTS support)
            pass
    logger.info("Schema migration complete")
