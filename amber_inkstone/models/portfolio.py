#!/usr/bin/env python3
"""
Data models for Amber Inkstone portfolio management.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class PeriodGroup:
    """A group of works sharing a canonical dynasty period."""
    period_slug: str          # e.g. "ming_dynasty"
    period_label: str         # e.g. "Ming Dynasty"
    work_numbers: List[str] = field(default_factory=list)
    work_count: int = 0
    top_themes: List[str] = field(default_factory=list)
    top_moods: List[str] = field(default_factory=list)
    century_breakdown: Dict[str, int] = field(default_factory=dict)
    thematic_subjects: List[str] = field(default_factory=list)


@dataclass
class ArtworkCandidate:
    """A candidate artwork returned from an API source."""
    url: str
    title: str
    source_api: str           # "wikimedia_commons" | "met_museum"
    license: str
    width: int = 0
    height: int = 0
    artist: str = ""
    medium: str = ""
    date_text: str = ""
    thumbnail_url: str = ""
    search_query: str = ""


@dataclass
class ArtworkImage:
    """An artwork downloaded and stored in the portfolio."""
    image_id: str             # md5 of source URL
    period_slug: str
    period_label: str
    source_url: str
    source_api: str
    title: str = ""
    artist: str = ""
    medium: str = ""
    date_text: str = ""
    license: str = ""
    width: int = 0
    height: int = 0
    cached_path: str = ""
    thumbnail_path: str = ""
    search_query: str = ""
    downloaded_at: Optional[datetime] = None
    user_rating: Optional[int] = None
    user_notes: str = ""


@dataclass
class ArtworkAssignment:
    """An assignment of an image to a specific work."""
    work_number: str
    image_id: str
    assigned_at: Optional[datetime] = None


@dataclass
class PeriodResearchResult:
    """Cached DeepSeek research for a dynasty period."""
    period_slug: str
    period_label: str
    art_styles: List[str] = field(default_factory=list)
    typical_subjects: List[str] = field(default_factory=list)
    typical_media: List[str] = field(default_factory=list)
    search_queries: List[str] = field(default_factory=list)
    top_themes: List[str] = field(default_factory=list)
    top_moods: List[str] = field(default_factory=list)
    century_breakdown: Dict[str, int] = field(default_factory=dict)
    thematic_subjects: List[str] = field(default_factory=list)
    researched_at: Optional[datetime] = None
