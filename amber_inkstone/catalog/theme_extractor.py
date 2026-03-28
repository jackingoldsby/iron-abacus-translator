#!/usr/bin/env python3
"""
Theme Extractor — aggregate thematic context per dynasty period from the DuckDB catalog.

Queries the catalog for all works in a period and extracts:
- Top themes across works
- Top moods across works
- Century breakdown (which centuries represented, with work counts)
- Subject hints mapped from wuxia themes to visual art subjects

Pure DuckDB + Python aggregation — no LLM needed.
"""

import logging
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config.defaults import DEFAULT_CATALOG_DB

logger = logging.getLogger(__name__)

# Map common wuxia/novel themes to visual art subject terms
THEME_SUBJECT_MAP: Dict[str, str] = {
    "romance": "man and woman couple lovers",
    "forbidden love": "man and woman secret meeting garden",
    "revenge": "warrior sword combat",
    "political intrigue": "court officials palace",
    "martial arts": "warriors swords martial combat",
    "brotherhood": "men group gathering",
    "master-disciple": "teacher student training",
    "family legacy": "family gathering generations",
    "wandering hero": "solitary traveler landscape road",
    "reclusion": "hermit mountain retreat solitude",
    "coming-of-age": "youth training journey",
    "dynastic collapse": "warfare siege battle",
    "ethnic conflict": "frontier border warfare cavalry",
    "calligraphy": "Chinese calligraphy brush ink scroll",
    "poetry": "calligraphy poem verse scroll",
    "scholarly": "scholar study calligraphy books",
}


def extract_themes_for_period(
    period_slug: str,
    catalog_db: Optional[Path] = None,
) -> Dict:
    """Extract thematic context for all works in a given dynasty period.

    Args:
        period_slug: Canonical period slug (e.g. "ming_dynasty")
        catalog_db: Override catalog DB path

    Returns:
        Dict with keys: top_themes, top_moods, century_breakdown, thematic_subjects
    """
    db_path = catalog_db or DEFAULT_CATALOG_DB
    if not db_path.exists():
        logger.warning(f"Catalog DB not found: {db_path}")
        return _empty_result()

    import duckdb

    conn = duckdb.connect(str(db_path), read_only=True)

    # Check which columns exist
    columns = {r[0] for r in conn.execute("DESCRIBE works").fetchall()}

    has_themes = "themes" in columns
    has_mood = "mood" in columns
    has_setting = "setting_period" in columns

    # Build query based on available columns
    select_parts = ["w.work_number"]
    if has_themes:
        select_parts.append("w.themes")
    if has_mood:
        select_parts.append("w.mood")
    if has_setting:
        select_parts.append("w.setting_period")

    query = f"""
        SELECT {', '.join(select_parts)}
        FROM works w
        LEFT JOIN work_series ws ON w.work_id = ws.work_id
        LEFT JOIN series s ON ws.series_id = s.series_id
    """

    rows = conn.execute(query).fetchall()
    conn.close()

    # Filter to works matching this period
    from config.dynasty_periods import normalize_period

    matching_rows = []
    for row in rows:
        idx = 1  # skip work_number
        themes_val = row[idx] if has_themes else None
        idx += 1 if has_themes else 0
        mood_val = row[idx] if has_mood else None
        idx += 1 if has_mood else 0
        setting_val = row[idx] if has_setting else None

        if setting_val:
            slug, _ = normalize_period(setting_val)
            if slug == period_slug:
                matching_rows.append({
                    "themes": themes_val or "",
                    "mood": mood_val or "",
                    "setting_period": setting_val or "",
                })

    if not matching_rows:
        logger.info(f"No works found for period {period_slug}")
        return _empty_result()

    # Aggregate themes
    theme_counter = Counter()
    for row in matching_rows:
        for theme in _split_field(row["themes"]):
            theme_counter[theme] += 1

    # Aggregate moods
    mood_counter = Counter()
    for row in matching_rows:
        for mood in _split_field(row["mood"]):
            mood_counter[mood] += 1

    # Century breakdown from setting_period text
    century_counter = Counter()
    for row in matching_rows:
        centuries = _extract_centuries(row["setting_period"])
        for c in centuries:
            century_counter[c] += 1

    # Map themes to visual subjects
    top_themes = [t for t, _ in theme_counter.most_common(10)]
    thematic_subjects = _map_themes_to_subjects(top_themes)

    result = {
        "top_themes": top_themes,
        "top_moods": [m for m, _ in mood_counter.most_common(5)],
        "century_breakdown": dict(century_counter.most_common()),
        "thematic_subjects": thematic_subjects,
    }

    logger.info(
        f"Extracted themes for {period_slug}: "
        f"{len(top_themes)} themes, {len(result['top_moods'])} moods, "
        f"{len(century_counter)} centuries, {len(thematic_subjects)} subjects"
    )
    return result


def _split_field(value: str) -> List[str]:
    """Split a comma/semicolon-separated field into normalized terms."""
    if not value:
        return []
    # Split on comma, semicolon, or " and "
    parts = re.split(r'[,;]\s*|\s+and\s+', value)
    return [p.strip().lower() for p in parts if p.strip()]


def _extract_centuries(setting_period: str) -> List[str]:
    """Extract century references from a setting_period string.

    Examples:
        "Ming Dynasty (15th century)" → ["15th century"]
        "Qing Dynasty, late 18th/early 19th century" → ["18th century", "19th century"]
        "Song-Yuan dynasties (12th-14th century)" → ["12th century", "13th century", "14th century"]
        "Ming Dynasty" → []  (no century info)
    """
    if not setting_period:
        return []

    text = setting_period.lower()
    centuries = []

    # Match patterns like "15th century", "15th-17th century", "15th/16th century"
    # Also handle ordinal numbers
    range_match = re.search(r'(\d{1,2})(?:st|nd|rd|th)\s*[-–/]\s*(?:\w+\s+)?(\d{1,2})(?:st|nd|rd|th)\s+centur', text)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        for c in range(start, end + 1):
            centuries.append(f"{_ordinal(c)} century")
        return centuries

    # Match individual century mentions
    for m in re.finditer(r'(\d{1,2})(?:st|nd|rd|th)\s+centur', text):
        c = int(m.group(1))
        centuries.append(f"{_ordinal(c)} century")

    return centuries


def _ordinal(n: int) -> str:
    """Convert integer to ordinal string."""
    if 11 <= n % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _map_themes_to_subjects(themes: List[str]) -> List[str]:
    """Map novel themes to visual art subject terms."""
    subjects = []
    seen = set()

    for theme in themes:
        theme_lower = theme.lower()
        for key, subject_terms in THEME_SUBJECT_MAP.items():
            if key in theme_lower or theme_lower in key:
                if subject_terms not in seen:
                    seen.add(subject_terms)
                    subjects.append(subject_terms)

    return subjects


def _empty_result() -> Dict:
    return {
        "top_themes": [],
        "top_moods": [],
        "century_breakdown": {},
        "thematic_subjects": [],
    }
