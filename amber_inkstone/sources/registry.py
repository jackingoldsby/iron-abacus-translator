#!/usr/bin/env python3
"""
Source registry — dispatch searches to configured sources.
"""

import logging
from typing import Dict, List, Type

from config.defaults import IMAGE_SOURCES
from models.portfolio import ArtworkCandidate
from sources.base import BaseSource
from sources.met_museum import MetMuseumSource
from sources.wikimedia import WikimediaSource

logger = logging.getLogger(__name__)

_SOURCE_CLASSES: Dict[str, Type[BaseSource]] = {
    "wikimedia_commons": WikimediaSource,
    "met_museum": MetMuseumSource,
}


def get_source(name: str) -> BaseSource:
    """Get a source instance by name."""
    cls = _SOURCE_CLASSES.get(name)
    if not cls:
        raise ValueError(f"Unknown source: {name}. Available: {list(_SOURCE_CLASSES.keys())}")
    return cls()


def search_all_sources(
    query: str,
    limit_per_source: int = 10,
    sources: List[str] | None = None,
) -> List[ArtworkCandidate]:
    """Search all configured sources and return combined results.

    Args:
        query: Search query string
        limit_per_source: Max results per source
        sources: Source names to use (default: IMAGE_SOURCES from config)

    Returns:
        Combined list of ArtworkCandidate from all sources
    """
    source_names = sources or IMAGE_SOURCES
    results = []

    for name in source_names:
        try:
            source = get_source(name)
            hits = source.search(query, limit=limit_per_source)
            results.extend(hits)
            logger.info(f"  {name}: {len(hits)} results for '{query}'")
        except Exception as e:
            logger.error(f"  {name} search failed: {e}")

    return results
