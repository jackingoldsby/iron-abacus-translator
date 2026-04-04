"""EPUB collection extractor — parses multi-book EPUB files."""

import logging
import re
from pathlib import Path
from typing import List

from ebooklib import epub

from detectors.toc_detector import detect_toc_type
from detectors.work_detector import (
    extract_works_flat_chapters,
    extract_works_flat_interleaved,
    extract_works_flat_single_doc,
    extract_works_hierarchical,
    extract_works_section_per_book,
)
from extractors.base import BaseExtractor
from models.core import DetectedWork
from transformers.encoding import S2T

logger = logging.getLogger(__name__)

# Strategy dispatch
STRATEGY_MAP = {
    "hierarchical_works": extract_works_hierarchical,
    "section_per_book": extract_works_section_per_book,
    "flat_chapters": extract_works_flat_chapters,
    "flat_single_doc": extract_works_flat_single_doc,
    "flat_interleaved": extract_works_flat_interleaved,
}


def extract_author_from_epub(book: epub.EpubBook, filename: str) -> str:
    """Extract author name (simplified) from EPUB metadata and filename."""
    creators = book.get_metadata("DC", "creator")
    if creators:
        author = creators[0][0].strip()
        if "&" in author:
            author = author.split("&")[0].strip()
        author = re.sub(r"\[.*?\]", "", author).strip()
        if author and len(author) <= 10 and author != "zhanghenshui":
            return author

    m = re.search(r"--\s*(.+?)\s*--", filename)
    if m:
        author = m.group(1).strip()
        if "&" in author:
            author = author.split("&")[0].strip()
        author = re.sub(r"\[.*?\]", "", author).strip()
        if author and author != "zhanghenshui":
            return author

    if "张恨水" in filename or "zhanghenshui" in filename.lower():
        return "张恨水"

    return ""


def extract_authors_from_epub(book: epub.EpubBook, filename: str) -> List[str]:
    """Extract all author names from multi-author collections."""
    authors = []

    creators = book.get_metadata("DC", "creator")
    if creators:
        for creator_tuple in creators:
            author = creator_tuple[0].strip()
            author = re.sub(r"\[.*?\]", "", author).strip()
            for a in re.split(r"\s*[&,;，；]\s*", author):
                a = a.strip()
                if a and a != "zhanghenshui" and len(a) <= 10:
                    authors.append(a)

    m = re.search(r"--\s*(.+?)\s*--", filename)
    if m:
        raw = m.group(1).strip()
        raw = re.sub(r"\[.*?\]", "", raw).strip()
        for a in re.split(r"\s*[&,;，；]\s*", raw):
            a = a.strip()
            if a and a not in authors and len(a) <= 10:
                authors.append(a)

    if not authors and ("张恨水" in filename or "zhanghenshui" in filename.lower()):
        authors.append("张恨水")

    return authors


class EpubExtractor(BaseExtractor):
    """Extracts works from multi-book EPUB collection files."""

    def supported_extensions(self) -> List[str]:
        return [".epub"]

    def extract_works(self, source_path: Path, author_hint: str = "") -> List[DetectedWork]:
        """Extract all works from an EPUB collection.

        Args:
            source_path: Path to the EPUB file.
            author_hint: Optional author name (simplified) override.

        Returns:
            List of detected works with chapters populated.
        """
        book = epub.read_epub(str(source_path))
        filename = source_path.name

        # Determine author
        if author_hint:
            author_simp = author_hint
        else:
            author_simp = extract_author_from_epub(book, filename)

        # Detect TOC structure and dispatch
        toc_type = detect_toc_type(book)
        logger.info(f"  TOC type: {toc_type}")

        strategy = STRATEGY_MAP.get(toc_type)
        if not strategy:
            logger.warning(f"  Unknown TOC type: {toc_type}")
            return []

        works = strategy(book, author_simp)

        # Stamp source on all works
        for w in works:
            w.source_epub = filename

        return works

    def get_toc_type(self, source_path: Path) -> str:
        """Detect TOC type without full extraction (for diagnostics)."""
        book = epub.read_epub(str(source_path))
        return detect_toc_type(book)

    def get_authors(self, source_path: Path) -> List[str]:
        """Extract all author names from an EPUB (for diagnostics)."""
        book = epub.read_epub(str(source_path))
        return extract_authors_from_epub(book, source_path.name)
