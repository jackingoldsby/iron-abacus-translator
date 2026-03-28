#!/usr/bin/env python3
"""
Glossary Appendix Generator

Generates a "Glossary of Terms" appendix from the FootnoteContextAccumulator
and TranslationGlossary database. Filters to include only terms with reference value
for the reader.

Usage:
    from utils.glossary_generator import generate_glossary_appendix

    entries = generate_glossary_appendix(accumulator, glossary, character_classifications)
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Categories to include in glossary (sorted display order)
GLOSSARY_CATEGORIES = [
    "Martial Arts & Techniques",
    "Internal Energy & Cultivation",
    "Weapons & Equipment",
    "Sects & Organizations",
    "Titles & Honorifics",
    "Historical & Cultural",
    "Places & Geography",
    "Historical Personages",
]

# Map from glossary DB categories to display categories
CATEGORY_MAP = {
    "martial_arts_techniques": "Martial Arts & Techniques",
    "martial_arts": "Martial Arts & Techniques",
    "techniques": "Martial Arts & Techniques",
    "combat": "Martial Arts & Techniques",
    "internal_energy": "Internal Energy & Cultivation",
    "cultivation": "Internal Energy & Cultivation",
    "qigong": "Internal Energy & Cultivation",
    "weapons": "Weapons & Equipment",
    "equipment": "Weapons & Equipment",
    "sects": "Sects & Organizations",
    "organizations": "Sects & Organizations",
    "clans": "Sects & Organizations",
    "titles": "Titles & Honorifics",
    "honorifics": "Titles & Honorifics",
    "social_terms": "Titles & Honorifics",
    "historical": "Historical & Cultural",
    "cultural": "Historical & Cultural",
    "customs": "Historical & Cultural",
    "dynasties": "Historical & Cultural",
    "places": "Places & Geography",
    "geography": "Places & Geography",
    "personages": "Historical Personages",
    "legendary": "Historical Personages",
}


@dataclass
class GlossaryAppendixEntry:
    """A single entry in the glossary appendix."""
    ideogram: str
    pinyin: str
    explanation: str
    category: str
    first_chapter: Optional[int] = None


def generate_glossary_appendix(
    accumulator: Any,
    glossary: Any = None,
    fictional_characters: Optional[Set[str]] = None,
    suppress_ideograms: Optional[Set[str]] = None,
) -> List[GlossaryAppendixEntry]:
    """
    Generate filtered glossary appendix entries.

    Inclusion filter (terms with reference value):
    - Martial arts techniques, styles, weapons, internal energy concepts
    - Clans, sects, schools
    - Historical/cultural terms
    - Significant place names
    - Historical and legendary personages

    Exclusion filter:
    - Fictional character names (from Stage 6a classification)
    - Common wuxia terms in suppress list
    - One-off contextual explanations without glossary entry

    Args:
        accumulator: FootnoteContextAccumulator with registered ideograms
        glossary: Optional TranslationGlossary for enriched metadata
        fictional_characters: Set of ideograms classified as fictional characters
        suppress_ideograms: Set of ideograms from suppress list (common terms)

    Returns:
        List of GlossaryAppendixEntry sorted by category then pinyin
    """
    fictional_characters = fictional_characters or set()
    suppress_ideograms = suppress_ideograms or set()

    entries: List[GlossaryAppendixEntry] = []
    seen_ideograms: Set[str] = set()

    all_footnoted = accumulator.all_footnoted_ideograms

    for ideogram in all_footnoted:
        # Skip fictional characters
        if ideogram in fictional_characters:
            continue

        # Skip suppressed common terms
        if ideogram in suppress_ideograms:
            continue

        # Skip duplicates
        if ideogram in seen_ideograms:
            continue

        first_chapter = accumulator.get_first_chapter(ideogram)

        # Try to get enriched info from glossary
        if glossary:
            gl_entry = glossary.lookup(ideogram)
            if gl_entry:
                category = _map_category(gl_entry.category)
                entries.append(GlossaryAppendixEntry(
                    ideogram=ideogram,
                    pinyin=gl_entry.pinyin,
                    explanation=gl_entry.footnote_template,
                    category=category,
                    first_chapter=first_chapter,
                ))
                seen_ideograms.add(ideogram)
                continue

        # No glossary entry -- skip (one-off contextual terms don't
        # belong in a glossary appendix)
        logger.debug(
            f"Skipping '{ideogram}' -- no glossary entry, likely contextual"
        )

    # Sort by category order, then by pinyin within category
    category_order = {cat: i for i, cat in enumerate(GLOSSARY_CATEGORIES)}
    entries.sort(
        key=lambda e: (
            category_order.get(e.category, 99),
            e.pinyin.lower(),
        )
    )

    logger.info(
        f"Generated glossary appendix: {len(entries)} entries "
        f"from {len(all_footnoted)} footnoted ideograms "
        f"({len(fictional_characters)} fictional excluded, "
        f"{len(suppress_ideograms)} suppressed)"
    )

    return entries


def _map_category(db_category: str) -> str:
    """Map a glossary DB category to a display category."""
    normalized = db_category.lower().replace(" ", "_").replace("-", "_")
    return CATEGORY_MAP.get(normalized, "Historical & Cultural")


def group_by_category(
    entries: List[GlossaryAppendixEntry],
) -> Dict[str, List[GlossaryAppendixEntry]]:
    """
    Group glossary entries by category for rendering.

    Args:
        entries: List of GlossaryAppendixEntry

    Returns:
        Dict mapping category name to list of entries
    """
    groups: Dict[str, List[GlossaryAppendixEntry]] = {}
    for entry in entries:
        groups.setdefault(entry.category, []).append(entry)
    return groups
