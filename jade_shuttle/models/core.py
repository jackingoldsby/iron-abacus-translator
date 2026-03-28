"""Core data models for jade_shuttle extraction pipeline."""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class Chapter:
    """A single chapter extracted from an ebook."""
    title: str
    content: List[Dict]  # [{"tag": "p", "content": "..."}, ...]


@dataclass
class DetectedWork:
    """A work detected within a collection ebook."""
    title_simplified: str
    title_traditional: str
    author_simplified: str
    author_traditional: str
    chapters: List[Chapter]
    volume_label: str = ""  # e.g., "上册" if this is a volume
    volume_group: str = ""  # base title for grouping volumes
    source_epub: str = ""
    character_count: int = 0

    def compute_character_count(self):
        total = 0
        for ch in self.chapters:
            for block in ch.content:
                total += len(block.get("content", ""))
        self.character_count = total


@dataclass
class WorkGroup:
    """A logical work that may span multiple volumes."""
    base_title_trad: str
    base_title_simp: str
    author_trad: str
    author_simp: str
    volumes: List[DetectedWork]  # Ordered volumes
    work_number: str = ""  # Assigned: A001, A002, ...
    directory_number: str = ""  # wuxia_XXXX number
    is_duplicate: bool = False
    matched_catalog_title: str = ""


@dataclass
class IngestReport:
    """Summary report of the ingestion."""
    epub_file: str
    author: str
    works_detected: int = 0
    works_new: int = 0
    works_duplicate: int = 0
    works_written: int = 0
    errors: List[str] = field(default_factory=list)
    work_details: List[Dict] = field(default_factory=list)
