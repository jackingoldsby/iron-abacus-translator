#!/usr/bin/env python3
"""
Glossary Renderer — groups glossary entries by category for EPUB rendering.

This module provides the grouping logic used by the EPUB builder.
The actual glossary *generation* (filtering footnotes into glossary entries)
stays in iron_abacus as utils/glossary_generator.py.
"""

from typing import Any, Dict, List


# Categories in display order
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


def group_by_category(
    entries: List[Any],
) -> Dict[str, List[Any]]:
    """
    Group glossary entries by category for rendering.

    Args:
        entries: List of GlossaryAppendixEntry (or any object with .category)

    Returns:
        Dict mapping category name to list of entries, ordered by
        GLOSSARY_CATEGORIES display order.
    """
    groups: Dict[str, List[Any]] = {}
    for entry in entries:
        cat = getattr(entry, "category", "Historical & Cultural")
        groups.setdefault(cat, []).append(entry)

    # Return in display order
    ordered: Dict[str, List[Any]] = {}
    for cat in GLOSSARY_CATEGORIES:
        if cat in groups:
            ordered[cat] = groups[cat]
    # Append any categories not in the standard list
    for cat, ents in groups.items():
        if cat not in ordered:
            ordered[cat] = ents

    return ordered
