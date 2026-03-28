#!/usr/bin/env python3
"""
Period Grouper — groups works from the DuckDB catalog by canonical dynasty period.

Reads setting_period from works and historical_period from series, normalizes
them to canonical slugs, and returns PeriodGroup objects.
"""

import logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from config.defaults import DEFAULT_CATALOG_DB
from config.dynasty_periods import normalize_period
from models.portfolio import PeriodGroup

logger = logging.getLogger(__name__)


def group_works_by_period(
    catalog_db: Optional[Path] = None,
) -> List[PeriodGroup]:
    """Query the works catalog and group works by normalized dynasty period.

    Uses works.setting_period as primary source, falls back to
    series.historical_period if available.

    Returns:
        List of PeriodGroup objects sorted by work count (descending).
    """
    db_path = catalog_db or DEFAULT_CATALOG_DB
    if not db_path.exists():
        logger.error(f"Catalog DB not found: {db_path}")
        return []

    import duckdb

    conn = duckdb.connect(str(db_path), read_only=True)

    rows = conn.execute("""
        SELECT w.work_number,
               w.setting_period,
               s.historical_period
        FROM works w
        LEFT JOIN work_series ws ON w.work_id = ws.work_id
        LEFT JOIN series s ON ws.series_id = s.series_id
    """).fetchall()
    conn.close()

    # Group by normalized period
    period_works: Dict[str, List[str]] = defaultdict(list)
    period_labels: Dict[str, str] = {}

    for work_number, setting_period, historical_period in rows:
        # Prefer setting_period, fall back to historical_period
        raw = setting_period or historical_period or ""
        slug, label = normalize_period(raw)
        period_works[slug].append(work_number)
        period_labels[slug] = label

    groups = []
    for slug, work_numbers in period_works.items():
        groups.append(PeriodGroup(
            period_slug=slug,
            period_label=period_labels[slug],
            work_numbers=work_numbers,
            work_count=len(work_numbers),
        ))

    groups.sort(key=lambda g: g.work_count, reverse=True)
    logger.info(f"Grouped {sum(g.work_count for g in groups)} works into {len(groups)} periods")
    return groups


def get_period_group(
    period_slug: str,
    catalog_db: Optional[Path] = None,
) -> Optional[PeriodGroup]:
    """Get a single period group by slug."""
    groups = group_works_by_period(catalog_db)
    for g in groups:
        if g.period_slug == period_slug:
            return g
    return None
