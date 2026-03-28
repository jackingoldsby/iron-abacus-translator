#!/usr/bin/env python3
"""
Query Generator — transforms period research into API search queries.

Uses the PeriodResearchResult (art styles, subjects, media, thematic context)
plus the artist whitelist to generate targeted search queries for Wikimedia
Commons and Met Museum.
"""

import logging
from typing import List

from config.dynasty_periods import get_whitelisted_artists
from models.portfolio import PeriodResearchResult

logger = logging.getLogger(__name__)


def generate_queries(
    research: PeriodResearchResult,
    max_queries: int = 15,
) -> List[str]:
    """Generate search queries from period research.

    Strategy (priority order):
    1. Artist + theme queries (highest signal — artist + thematic subject)
    2. Century-specific queries (targeted time period)
    3. Theme-mapped subject queries (novel themes → visual subjects)
    4. Style + subject combination queries (from DeepSeek research)
    5. Dynasty + medium queries
    6. General fallback

    Args:
        research: Period research result (may include thematic context)
        max_queries: Maximum number of queries to generate

    Returns:
        List of search query strings
    """
    queries = []
    period_label = research.period_label

    artists = get_whitelisted_artists(research.period_slug)
    has_themes = bool(research.thematic_subjects)
    has_centuries = bool(research.century_breakdown)

    # 1. Artist + theme queries (highest signal)
    if artists and has_themes:
        for artist in artists[:3]:
            # Pick first thematic subject, take first 2-3 words
            subject_words = research.thematic_subjects[0].split()[:3]
            queries.append(f"{artist} {' '.join(subject_words)} painting")

    # 2. Plain artist queries
    for artist in artists[:4]:
        queries.append(f"{artist} Chinese painting")

    # 3. Century-specific queries
    if has_centuries:
        for century in list(research.century_breakdown.keys())[:2]:
            queries.append(f"{century} Chinese painting")
            queries.append(f"{period_label} {century} scroll")

    # 4. Theme-mapped subject queries
    if has_themes:
        for subject_terms in research.thematic_subjects[:3]:
            # Take key words from subject terms
            key_words = subject_terms.split()[:4]
            queries.append(f"Chinese painting {' '.join(key_words)} {period_label}")

    # 5. Style + subject combinations (from DeepSeek research)
    styles = research.art_styles[:3]
    subjects = research.typical_subjects[:4]

    for style in styles:
        queries.append(f"Chinese {style} {period_label}")

    for subject in subjects[:3]:
        queries.append(f"{period_label} {subject} painting")

    # 6. Dynasty + medium queries
    for medium in research.typical_media[:2]:
        queries.append(f"Chinese {medium} {period_label}")

    # 7. Calligraphy queries (period calligraphy makes excellent cover art)
    queries.append(f"{period_label} Chinese calligraphy scroll")

    # 8. General dynasty query as fallback
    queries.append(f"{period_label} Chinese painting scroll")

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for q in queries:
        q_lower = q.lower()
        if q_lower not in seen:
            seen.add(q_lower)
            unique.append(q)

    result = unique[:max_queries]
    logger.info(f"Generated {len(result)} search queries for {period_label}")
    return result
