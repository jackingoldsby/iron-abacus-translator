#!/usr/bin/env python3
"""
Catalog lookup utilities for Crimson Folio.

Reads series metadata, English titles, and author info from the shared
DuckDB catalog without importing from iron_abacus.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def lookup_catalog(
    work_number: str, catalog_db: Optional[Path] = None
) -> Dict[str, Any]:
    """Look up title, author, series, and edition info from catalog DB.

    Args:
        work_number: Work identifier (e.g. "D1379")
        catalog_db: Path to DuckDB catalog file

    Returns:
        Dict with title_english, author_english, series_name, series_order,
        series_total, edition fields (all optional).
    """
    if catalog_db is None:
        from config.defaults import DEFAULT_CATALOG_DB
        catalog_db = DEFAULT_CATALOG_DB

    if not catalog_db or not catalog_db.exists():
        return {}

    try:
        import duckdb

        conn = duckdb.connect(str(catalog_db), read_only=True)
        result = conn.execute("""
            SELECT COALESCE(wct.consensus_title_english, w.title_english) as title_en,
                   COALESCE(wct.consensus_author_english, w.author_english) as author_en,
                   s.name_english, ws.order_in_series,
                   (SELECT COUNT(*) FROM work_series ws2
                    WHERE ws2.series_id = ws.series_id) as total,
                   w.edition
            FROM works w
            LEFT JOIN works_consensus_translations wct ON w.work_id = wct.work_id
            LEFT JOIN work_series ws ON w.work_id = ws.work_id
            LEFT JOIN series s ON ws.series_id = s.series_id
            WHERE w.work_number = ?
        """, (work_number,)).fetchone()
        conn.close()

        if result:
            data = {
                "title_english": result[0] or "",
                "author_english": result[1] or "",
            }
            if result[2]:  # series name
                data["series_name"] = result[2]
                data["series_order"] = result[3]
                data["series_total"] = result[4]
            if result[5]:  # edition
                data["edition"] = result[5]
            return data
    except Exception as e:
        logger.warning(f"Catalog lookup failed for {work_number}: {e}")

    return {}


def lookup_series(work_number: str, catalog_db: Optional[Path] = None) -> Dict[str, Any]:
    """Look up series info from catalog DB by work_number."""
    catalog = lookup_catalog(work_number, catalog_db)
    if catalog.get("series_name"):
        return {
            "name": catalog["series_name"],
            "order": catalog["series_order"],
            "total": catalog["series_total"],
        }
    return {}
