"""Core data models for cobalt_loom scraping pipeline."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ScrapedChapter:
    """A single chapter scraped from a web source."""
    title: str
    content: List[Dict]  # [{"tag": "p", "content": "..."}, ...]
    source_url: str = ""
    character_count: int = 0

    def compute_character_count(self):
        total = 0
        for block in self.content:
            total += len(block.get("content", ""))
        self.character_count = total


@dataclass
class ScrapedWork:
    """A complete work scraped from Wikisource or ctext.org."""
    work_number: str  # e.g., "A005"
    title: str  # Traditional Chinese title
    author: str  # Traditional Chinese author
    chapters: List[ScrapedChapter]
    source: str  # "wikisource" or "ctext"
    source_url: str = ""
    character_count: int = 0
    directory_number: str = ""  # e.g., "0644"

    def compute_character_count(self):
        total = 0
        for ch in self.chapters:
            ch.compute_character_count()
            total += ch.character_count
        self.character_count = total


@dataclass
class ScrapeReport:
    """Summary report of a scraping run."""
    work_number: str
    title: str = ""
    source: str = ""
    chapters_discovered: int = 0
    chapters_scraped: int = 0
    chapters_skipped: int = 0
    character_count: int = 0
    errors: List[str] = field(default_factory=list)
    dry_run: bool = False
