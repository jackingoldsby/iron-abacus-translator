#!/usr/bin/env python3
"""
EPUB Collection Ingester

Parses multi-book EPUB collections from Anna's Archive, splits them into
individual works, converts to the pipeline's raw JSON format, and registers
them in the DuckDB catalog.

Handles several TOC structures:
  - Hierarchical (Huang Yi): sections = works, sub-sections = volumes
  - Section-per-book (Liang Yusheng, Wolong Sheng): each section = one book
  - Flat single-doc (Xiao Yi, Wen Ruian): each TOC leaf = an entire book
  - Flat chapter-interleaved (Sima Ling): book titles + chapters interleaved

Usage:
    python dev/admin/ingest_epub_collections.py --dry-run
    python dev/admin/ingest_epub_collections.py --single "萧逸*.epub" --dry-run
    python dev/admin/ingest_epub_collections.py
"""

import argparse
import fnmatch
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Resolve paths
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "iron_abacus_translator"))

import duckdb
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import opencc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Defaults
DEFAULT_EPUB_DIR = "/Users/jacki/project_files/translation_project/for_parsing/"
DEFAULT_OUTPUT_DIR = "/Users/jacki/project_files/translation_project/work_individual_files/"
DEFAULT_DB_PATH = "/Users/jacki/project_files/translation_project/db/works_translator.duckdb"

# OpenCC converter: simplified -> traditional
S2T = opencc.OpenCC("s2t")
T2S = opencc.OpenCC("t2s")

# Volume markers to strip when grouping multi-volume works
VOLUME_MARKERS = re.compile(
    r"[（(]?(?:上册?|中册?|下册?|第[一二三四五六七八九十\d]+册|卷[一二三四五六七八九十\d]+)[)）]?$"
)

# Patterns indicating non-chapter front/back matter
SKIP_TITLES = {
    "版权信息", "版權信息", "梁羽生先生简介", "梁羽生先生簡介",
    "梁羽生武侠小说作品集", "梁羽生武俠小說作品集",
    "目录", "目錄", "封面", "书名", "書名", "新版电子书序言",
    "新版電子書序言", "前言", "后记", "後記", "附录", "附錄",
}

# Known author mappings (traditional -> simplified)
# Reused from annas_archive_gap_finder.py
AUTHOR_MAP = {
    "溫瑞安": "温瑞安",
    "蕭逸": "萧逸",
    "陳青雲": "陈青云",
    "柳殘陽": "柳残阳",
    "臥龍生": "卧龙生",
    "司馬翎": "司马翎",
    "黃易": "黄易",
    "梁羽生": "梁羽生",
    "諸葛青雲": "诸葛青云",
    "還珠樓主": "还珠楼主",
    "顧明道": "顾明道",
    "鄭證因": "郑证因",
    "張恨水": "张恨水",
}

# Reverse map
AUTHOR_MAP_S2T = {v: k for k, v in AUTHOR_MAP.items()}


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Chapter:
    """A single chapter extracted from EPUB."""
    title: str
    content: List[Dict]  # [{"tag": "p", "content": "..."}, ...]


@dataclass
class DetectedWork:
    """A work detected within a collection EPUB."""
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
    directory_number: str = ""  # work_XXXX number
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


# ── EPUB Parsing ──────────────────────────────────────────────────────────────

def html_to_blocks(html_content: bytes, strip_nav: bool = True) -> List[Dict]:
    """Convert EPUB HTML content to a list of tag/content blocks."""
    soup = BeautifulSoup(html_content, "html.parser")
    body = soup.find("body")
    if not body:
        body = soup

    blocks = []
    for el in body.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "div", "blockquote"]):
        text = el.get_text(strip=True)
        if not text:
            continue
        tag = el.name
        # Collapse div to p for pipeline compatibility
        if tag == "div":
            tag = "p"
        blocks.append({"tag": tag, "content": text})

    return blocks


def get_item_content(book: epub.EpubBook, href: str) -> bytes:
    """Get content of an EPUB item by href (handles fragment anchors)."""
    # Strip fragment
    base_href = href.split("#")[0]
    item = book.get_item_with_href(base_href)
    if item is None:
        # Try matching by name
        for it in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            if it.get_name().endswith(base_href):
                item = it
                break
    if item is None:
        return b""
    return item.get_content()


def split_content_by_fragment(html_content: bytes, fragment: str) -> List[Dict]:
    """Extract content starting from a specific fragment anchor.

    For EPUBs where multiple sections share the same HTML file but use
    different fragment anchors (e.g., chapter1.html#sec1, chapter1.html#sec2).
    Returns blocks from the fragment anchor to the next anchor of the same level.
    """
    if not fragment:
        return html_to_blocks(html_content)

    soup = BeautifulSoup(html_content, "html.parser")

    # Find the anchor element
    anchor = soup.find(id=fragment) or soup.find("a", attrs={"name": fragment})
    if not anchor:
        # If fragment looks like filepos, try to find by text position marker
        if fragment.startswith("filepos"):
            return html_to_blocks(html_content)
        return html_to_blocks(html_content)

    # Collect elements after this anchor until the next anchor of similar type
    blocks = []
    current = anchor
    # Include the anchor element itself if it has text
    anchor_text = anchor.get_text(strip=True)
    if anchor_text:
        blocks.append({"tag": anchor.name if anchor.name in ("h1", "h2", "h3", "h4", "p") else "p",
                        "content": anchor_text})

    # Walk siblings
    for sibling in anchor.find_next_siblings():
        # Stop at next sigil_toc_id anchor (next section boundary)
        if sibling.get("id", "").startswith("sigil_toc_id"):
            break
        text = sibling.get_text(strip=True)
        if text:
            tag = sibling.name if sibling.name in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote") else "p"
            blocks.append({"tag": tag, "content": text})

    return blocks


def get_toc_leaves(toc_items) -> List:
    """Flatten TOC to leaf entries."""
    leaves = []
    for item in toc_items:
        if isinstance(item, tuple):
            leaves.extend(get_toc_leaves(item[1]))
        else:
            leaves.append(item)
    return leaves


def get_toc_top_level(toc_items) -> List:
    """Get top-level TOC entries (sections or leaves)."""
    return list(toc_items)


# ── TOC Structure Detection ──────────────────────────────────────────────────

def detect_toc_type(book: epub.EpubBook) -> str:
    """Detect the TOC structure type.

    Returns one of:
      'hierarchical_works'  — top sections are works (Huang Yi, Guzhengxia)
      'section_per_book'    — sections are books, children are chapters (Liang Yusheng, Wolong Sheng)
      'flat_single_doc'     — each leaf is an entire book in one HTML file (Xiao Yi, Wen Ruian)
      'flat_interleaved'    — flat leaves mixing book titles and chapters (Sima Ling, Liu Canyang)
    """
    toc = book.toc
    if not toc:
        return "flat_single_doc"

    # Count sections vs leaves at top level
    sections = []
    leaves = []
    for item in toc:
        if isinstance(item, tuple):
            sections.append(item)
        else:
            leaves.append(item)

    # Pure sections at top level
    if sections and not leaves:
        # Check if sub-sections exist (Huang Yi has work > volume > chapter)
        has_subsections = False
        for sec, children in sections:
            for child in children:
                if isinstance(child, tuple):
                    has_subsections = True
                    break
            if has_subsections:
                break

        if has_subsections:
            return "hierarchical_works"
        return "section_per_book"

    # Mixed or pure leaves
    if not sections and leaves:
        # Check if leaves share HTML files (flat interleaved)
        hrefs = set()
        unique_base_hrefs = set()
        for leaf in leaves:
            base = leaf.href.split("#")[0] if leaf.href else ""
            unique_base_hrefs.add(base)

        # If many leaves map to few HTML files, it's interleaved
        if len(unique_base_hrefs) < len(leaves) * 0.5:
            return "flat_interleaved"

        # If each leaf maps to its own file (or very few share), it's single-doc
        return "flat_single_doc"

    # Mixed sections and leaves
    if sections and leaves:
        # Probably hierarchical with some standalone leaves (cover, preface)
        return "hierarchical_works"

    return "flat_single_doc"


# ── Work Detection Strategies ────────────────────────────────────────────────

def is_chapter_title(title: str) -> bool:
    """Check if a title looks like a chapter heading rather than a book title."""
    if not title:
        return False
    title = title.strip()
    # Chapter patterns: 第X回, 第X章, 楔子, 尾声, 引子, 序章, 后记
    return bool(re.match(
        r"^(第[一二三四五六七八九十百零\d]+[回章節节]|楔子|尾聲|尾声|引子|序[章曲]|後記|后记|前言|附錄|附录|"
        r"故事[简簡]介|[梁溫温蕭萧][^　]{1,3}先生[简簡]介|"
        r"[梁溫温蕭萧][^　]{1,3}武[侠俠]小[说說]作品集|版[权權]信息|目[录錄]|封面)",
        title,
    ))


def is_skip_title(title: str) -> bool:
    """Check if title should be skipped (front/back matter)."""
    return title.strip() in SKIP_TITLES


def _is_generic_volume_title(title: str) -> bool:
    """Check if a title is a generic volume label (not a work title).

    Examples of generic: "第一卷", "卷二", "上卷", "下卷",
                         "第一卷 魔女国" (numbered volume with subtitle)
    Examples of NOT generic: "寻秦记·第一册", "凌渡宇合集·第一册 月魔"
    """
    t = title.strip()
    return bool(re.match(
        r"^(第[一二三四五六七八九十百零\d]+[卷册冊](\s+.+)?|"
        r"卷[一二三四五六七八九十百零\d]+|"
        r"[上中下][卷册冊]?)$",
        t,
    ))


def _unwrap_single_child_sections(section_title: str, children: list) -> Tuple[str, list]:
    """Recursively unwrap sections that contain a single child section.

    Some EPUBs nest: Work > Work (duplicate) > Volume > Chapter.
    We unwrap until we find either leaves or multiple child sections.
    """
    while True:
        sections = [c for c in children if isinstance(c, tuple)]
        leaves = [c for c in children if not isinstance(c, tuple)]

        # If there's exactly one child section and no leaves, unwrap it
        if len(sections) == 1 and not leaves:
            child_sec, child_children = sections[0]
            # Keep the more specific title
            section_title = child_sec.title.strip() if child_sec.title else section_title
            children = child_children
        else:
            break

    return section_title, children


def _extract_work_from_section(
    book: epub.EpubBook,
    work_title: str,
    children: list,
    author_simp: str,
    author_trad: str,
) -> List[DetectedWork]:
    """Extract works from a TOC section and its children.

    Handles:
    - Section with leaf children (single volume)
    - Section with sub-section children (multi-volume, each sub-section = volume)
    - Deeply nested sections (unwrapped first)
    """
    results = []

    # Unwrap redundant single-child nesting
    work_title, children = _unwrap_single_child_sections(work_title, children)

    # Check if children are sections (volumes) or leaves (chapters)
    has_subsections = any(isinstance(c, tuple) for c in children)

    if has_subsections:
        # Children are volume sections — collect chapter leaves from each
        for child in children:
            if isinstance(child, tuple):
                vol_section, vol_children = child
                vol_title = vol_section.title.strip() if vol_section.title else work_title

                # Recursively unwrap volume sub-sections too
                vol_title, vol_children = _unwrap_single_child_sections(vol_title, vol_children)

                # If vol_title is generic ("第一卷", "上卷", etc.) prefix with work title
                if _is_generic_volume_title(vol_title):
                    vol_title = f"{work_title}·{vol_title}"

                # Collect all leaves recursively
                all_leaves = _collect_leaves_recursive(vol_children)
                chapters = _extract_chapters_from_leaves(book, all_leaves)
                if chapters:
                    title_simp = vol_title
                    title_trad = S2T.convert(title_simp)
                    detected = DetectedWork(
                        title_simplified=title_simp,
                        title_traditional=title_trad,
                        author_simplified=author_simp,
                        author_traditional=author_trad,
                        chapters=chapters,
                        volume_group=work_title,
                    )
                    detected.compute_character_count()
                    results.append(detected)
    else:
        # Single-volume work — children are chapter leaves
        chapter_leaves = [c for c in children if not isinstance(c, tuple)]
        chapters = _extract_chapters_from_leaves(book, chapter_leaves)
        if chapters:
            title_simp = work_title
            title_trad = S2T.convert(title_simp)
            detected = DetectedWork(
                title_simplified=title_simp,
                title_traditional=title_trad,
                author_simplified=author_simp,
                author_traditional=author_trad,
                chapters=chapters,
            )
            detected.compute_character_count()
            results.append(detected)

    return results


def _collect_leaves_recursive(items: list) -> list:
    """Recursively collect all leaf (non-tuple) items from a TOC tree."""
    leaves = []
    for item in items:
        if isinstance(item, tuple):
            _, children = item
            leaves.extend(_collect_leaves_recursive(children))
        else:
            leaves.append(item)
    return leaves


def extract_works_hierarchical(book: epub.EpubBook, author_simp: str) -> List[DetectedWork]:
    """Extract works from hierarchical TOC (e.g., Huang Yi, Guzhengxia).

    Structure: Section(work) > Section(volume) > Leaf(chapter)
    or: Section(work) > Leaf(chapter)
    Handles arbitrary nesting depth by unwrapping single-child sections.
    """
    works = []
    author_trad = S2T.convert(author_simp)

    for item in book.toc:
        if not isinstance(item, tuple):
            continue  # Skip standalone leaves (cover, preface)
        section, children = item
        work_title = section.title.strip() if section.title else ""
        if not work_title or is_skip_title(work_title):
            continue

        extracted = _extract_work_from_section(
            book, work_title, children, author_simp, author_trad
        )
        works.extend(extracted)

    return works


def extract_works_section_per_book(book: epub.EpubBook, author_simp: str) -> List[DetectedWork]:
    """Extract works where each TOC section = one book (e.g., Liang Yusheng)."""
    works = []
    author_trad = S2T.convert(author_simp)

    for item in book.toc:
        if not isinstance(item, tuple):
            continue
        section, children = item
        work_title = section.title.strip() if section.title else ""
        if not work_title or is_skip_title(work_title):
            continue

        # Children are chapter leaves (skip front/back matter leaves)
        chapter_leaves = []
        for child in children:
            if isinstance(child, tuple):
                # Nested section — recurse into it
                _, nested = child
                chapter_leaves.extend([c for c in nested if not isinstance(c, tuple)])
            else:
                title = child.title.strip() if child.title else ""
                if not is_skip_title(title):
                    chapter_leaves.append(child)

        chapters = _extract_chapters_from_leaves(book, chapter_leaves)
        if chapters:
            title_simp = work_title
            title_trad = S2T.convert(title_simp)
            detected = DetectedWork(
                title_simplified=title_simp,
                title_traditional=title_trad,
                author_simplified=author_simp,
                author_traditional=author_trad,
                chapters=chapters,
            )
            detected.compute_character_count()
            works.append(detected)

    return works


def _build_spine_index(book: epub.EpubBook) -> List[str]:
    """Build ordered list of spine item hrefs (base, no fragment)."""
    spine_hrefs = []
    for idref, linear in book.spine:
        item = book.get_item_with_id(idref)
        if item:
            spine_hrefs.append(item.get_name())
    return spine_hrefs


def _get_multi_file_content(book: epub.EpubBook, start_href: str, end_href: str,
                             spine_hrefs: List[str]) -> List[Dict]:
    """Get content spanning multiple spine files from start_href to end_href (exclusive)."""
    start_base = start_href.split("#")[0]
    end_base = end_href.split("#")[0] if end_href else None

    try:
        start_idx = spine_hrefs.index(start_base)
    except ValueError:
        return []

    if end_base:
        try:
            end_idx = spine_hrefs.index(end_base)
        except ValueError:
            end_idx = len(spine_hrefs)
    else:
        end_idx = len(spine_hrefs)

    all_blocks = []
    for href in spine_hrefs[start_idx:end_idx]:
        content = get_item_content(book, href)
        if content:
            blocks = html_to_blocks(content)
            all_blocks.extend(blocks)

    return all_blocks


def extract_works_flat_single_doc(book: epub.EpubBook, author_simp: str) -> List[DetectedWork]:
    """Extract works where each TOC leaf = an entire book (e.g., Wen Ruian, Xiao Yi).

    Each leaf may point to a single large HTML file (Xiao Yi) or span multiple
    spine items (Wen Ruian). We collect all content between consecutive TOC entries
    and split into chapters by detecting heading patterns.
    """
    works = []
    author_trad = S2T.convert(author_simp)

    # Build spine index for multi-file content collection
    spine_hrefs = _build_spine_index(book)

    # Get all flat leaves
    leaves = [item for item in book.toc if not isinstance(item, tuple)]

    for i, leaf in enumerate(leaves):
        title = leaf.title.strip() if leaf.title else ""
        if not title or is_skip_title(title):
            continue

        # Determine content range
        next_href = leaves[i + 1].href if i + 1 < len(leaves) else None

        # Try single-file content first
        content = get_item_content(book, leaf.href)
        single_file_blocks = html_to_blocks(content) if content else []
        single_file_chars = sum(len(b.get("content", "")) for b in single_file_blocks)

        if single_file_chars > 5000:
            # Content is in a single file — use it directly
            all_blocks = single_file_blocks
        else:
            # Content spans multiple spine items — collect from spine
            all_blocks = _get_multi_file_content(book, leaf.href, next_href, spine_hrefs)

        if not all_blocks:
            continue

        # Split into chapters by detecting chapter headings
        chapters = _split_blocks_into_chapters(all_blocks, title)

        if chapters:
            title_simp = title
            title_trad = S2T.convert(title_simp)
            detected = DetectedWork(
                title_simplified=title_simp,
                title_traditional=title_trad,
                author_simplified=author_simp,
                author_traditional=author_trad,
                chapters=chapters,
            )
            detected.compute_character_count()
            works.append(detected)

    return works


def extract_works_flat_interleaved(book: epub.EpubBook, author_simp: str) -> List[DetectedWork]:
    """Extract works from flat interleaved TOC (e.g., Sima Ling, Liu Canyang).

    TOC has book titles and chapter titles mixed together. Book titles are
    non-chapter entries followed by chapter entries.
    """
    works = []
    author_trad = S2T.convert(author_simp)

    leaves = get_toc_leaves(book.toc)

    # Group consecutive leaves: a book title followed by its chapters
    current_work_title = None
    current_chapters: List = []

    def flush_work():
        nonlocal current_work_title, current_chapters
        if current_work_title and current_chapters:
            chapters = _extract_chapters_from_leaves(book, current_chapters)
            if chapters:
                title_simp = current_work_title
                title_trad = S2T.convert(title_simp)
                detected = DetectedWork(
                    title_simplified=title_simp,
                    title_traditional=title_trad,
                    author_simplified=author_simp,
                    author_traditional=author_trad,
                    chapters=chapters,
                )
                detected.compute_character_count()
                works.append(detected)
        current_work_title = None
        current_chapters = []

    for leaf in leaves:
        title = leaf.title.strip() if leaf.title else ""
        if not title or is_skip_title(title):
            continue

        if is_chapter_title(title):
            # This is a chapter — add to current work
            if current_work_title is None:
                # Orphan chapter — create unnamed work
                current_work_title = title
            current_chapters.append(leaf)
        else:
            # This looks like a book title — start new work
            flush_work()
            current_work_title = title
            # Check if this leaf's content has chapters embedded
            # (some EPUBs put the entire book in one HTML file pointed to by the title leaf)
            content = get_item_content(book, leaf.href)
            if content:
                blocks = html_to_blocks(content)
                # If it has substantial content, it might be a single-doc work
                total_chars = sum(len(b.get("content", "")) for b in blocks)
                if total_chars > 5000:
                    # Treat as single-doc — the "chapters" in TOC are just anchors
                    pass  # We'll collect the chapter leaves that follow

    flush_work()
    return works


def _extract_chapters_from_leaves(book: epub.EpubBook, leaves: list) -> List[Chapter]:
    """Extract chapter content from TOC leaf items."""
    chapters = []
    seen_hrefs = set()

    for leaf in leaves:
        title = leaf.title.strip() if leaf.title else ""
        href = leaf.href if leaf.href else ""

        if not href:
            continue

        # Skip exact duplicate hrefs (same content referenced twice)
        base_href = href.split("#")[0]
        fragment = href.split("#")[1] if "#" in href else ""

        content = get_item_content(book, href)
        if not content:
            continue

        # If there's a fragment, try to extract just that section
        if fragment and fragment not in ("chapter", ""):
            blocks = split_content_by_fragment(content, fragment)
        else:
            # Check if this href was already seen (shared HTML file)
            if base_href in seen_hrefs and not fragment:
                continue
            blocks = html_to_blocks(content)

        seen_hrefs.add(base_href)

        if blocks:
            # Use leaf title if available, otherwise first heading
            ch_title = title
            if not ch_title and blocks and blocks[0].get("tag", "").startswith("h"):
                ch_title = blocks[0]["content"]

            chapters.append(Chapter(title=ch_title, content=blocks))

    return chapters


def _split_blocks_into_chapters(blocks: List[Dict], work_title: str) -> List[Chapter]:
    """Split a flat list of blocks into chapters by detecting heading patterns."""
    # Pattern for chapter headings
    chapter_re = re.compile(
        r"^(第[一二三四五六七八九十百零\d]+[回章節节]|楔子|尾聲|尾声|引子|序[章曲])"
    )

    chapters = []
    current_title = work_title
    current_blocks: List[Dict] = []

    for block in blocks:
        text = block.get("content", "").strip()

        # Check if this block is a chapter heading
        if chapter_re.match(text) or (block.get("tag", "").startswith("h") and len(text) < 60):
            # Flush previous chapter
            if current_blocks:
                chapters.append(Chapter(title=current_title, content=current_blocks))
            current_title = text
            current_blocks = []
        else:
            current_blocks.append(block)

    # Flush last chapter
    if current_blocks:
        chapters.append(Chapter(title=current_title, content=current_blocks))

    return chapters


# ── Volume Grouping ──────────────────────────────────────────────────────────

def strip_volume_marker(title: str) -> Tuple[str, str]:
    """Strip volume markers from title, return (base_title, volume_marker).

    Examples:
        "七剑下天山（上册）" -> ("七剑下天山", "上册")
        "江湖三女侠（中册）" -> ("江湖三女侠", "中册")
        "风尘侠隐鹰爪王10" -> ("风尘侠隐鹰爪王", "10")
        "荒江女侠十七" -> ("荒江女侠", "十七")
        "白发魔女传" -> ("白发魔女传", "")
    """
    # Try common volume patterns (order matters — most specific first)
    patterns = [
        # Parenthesized: （上册）, (第三册)
        (r"[（(]([上中下])[册冊]?[)）]$", r"[（(][上中下][册冊]?[)）]$"),
        (r"[（(]第([一二三四五六七八九十\d]+)[册冊卷][)）]$", r"[（(]第[一二三四五六七八九十\d]+[册冊卷][)）]$"),
        # Suffix: ·上册, 上册
        (r"·?([上中下])[册冊]?$", r"·?[上中下][册冊]?$"),
        (r"·?第([一二三四五六七八九十\d]+)[册冊卷]$", r"·?第[一二三四五六七八九十\d]+[册冊卷]$"),
        # "·第N册 Subtitle" pattern: 凌渡宇合集·第一册 月魔
        (r"·第[一二三四五六七八九十\d]+[册冊]\s*.+$", r"·第[一二三四五六七八九十\d]+[册冊]\s*.+$"),
        # "·第N卷 Subtitle" pattern: 大剑师传奇·第一卷 魔女国
        (r"·第[一二三四五六七八九十\d]+[卷]\s*.+$", r"·第[一二三四五六七八九十\d]+[卷]\s*.+$"),
        # "·卷N" pattern: 天地明环·卷二
        (r"·卷[一二三四五六七八九十\d]+$", r"·卷[一二三四五六七八九十\d]+$"),
        # Chinese numeral suffix: 荒江女侠十七, 鹰爪王一
        (r"([一二三四五六七八九十百]+)$", r"[一二三四五六七八九十百]+$"),
        # Arabic numeral suffix: 鹰爪王10, 鹰爪王1
        (r"(\d+)$", r"\d+$"),
    ]

    for capture_re, strip_re in patterns:
        m = re.search(capture_re, title)
        if m:
            base = re.sub(strip_re, "", title).strip()
            marker = m.group(0)
            # Avoid stripping if base becomes too short (< 2 chars)
            # or if the "marker" is actually part of the title
            if len(base) >= 2:
                return base, marker

    return title, ""


def group_volumes(works: List[DetectedWork]) -> List[WorkGroup]:
    """Group detected works into logical works with volumes."""
    # First pass: strip volume markers and group
    groups: Dict[str, List[DetectedWork]] = {}
    order: List[str] = []

    for work in works:
        base, marker = strip_volume_marker(work.title_simplified)
        work.volume_label = marker
        work.volume_group = base

        if base not in groups:
            groups[base] = []
            order.append(base)
        groups[base].append(work)

    # Create WorkGroup objects
    result = []
    for base_title in order:
        vols = groups[base_title]
        author_simp = vols[0].author_simplified
        author_trad = vols[0].author_traditional
        base_trad = S2T.convert(base_title)

        group = WorkGroup(
            base_title_trad=base_trad,
            base_title_simp=base_title,
            author_trad=author_trad,
            author_simp=author_simp,
            volumes=vols,
        )
        result.append(group)

    return result


# ── Catalog Matching ─────────────────────────────────────────────────────────

def normalize_title(t: str) -> str:
    """Normalize a title for comparison."""
    t = re.sub(r"[（()）\[\]【】《》\s·．.、，,：:\"\"''「」]", "", t)
    return t.lower()


def load_catalog(db_path: str) -> Tuple[List[Dict], Set[str]]:
    """Load works and authors from catalog.

    Returns (works_list, author_names_set).
    """
    con = duckdb.connect(db_path, read_only=True)
    rows = con.execute(
        "SELECT work_id, work_number, title_chinese, author_chinese, title_author, directory_number "
        "FROM works"
    ).fetchall()
    works = []
    authors = set()
    for r in rows:
        works.append({
            "work_id": r[0],
            "work_number": r[1],
            "title_chinese": r[2],
            "author_chinese": r[3],
            "title_author": r[4],
            "directory_number": r[5],
        })
        if r[3]:
            authors.add(r[3])
    con.close()
    return works, authors


def title_matches_catalog(
    work_title: str,
    catalog_works: List[Dict],
    author_trad: str = "",
    author_simp: str = "",
) -> Optional[Dict]:
    """Check if a work title matches any catalog entry.

    Returns the matched catalog work dict or None.
    """
    norm_title = normalize_title(work_title)
    if len(norm_title) < 2:
        return None

    # Also try traditional and simplified variants
    title_variants = {norm_title}
    title_variants.add(normalize_title(S2T.convert(work_title)))
    title_variants.add(normalize_title(T2S.convert(work_title)))

    for cat_work in catalog_works:
        cat_title = cat_work.get("title_chinese", "") or ""
        cat_author = cat_work.get("author_chinese", "") or ""
        cat_norm = normalize_title(cat_title)

        if len(cat_norm) < 2:
            continue

        # Check if author matches (if specified)
        author_match = True
        if author_trad and cat_author:
            author_match = cat_author in (author_trad, author_simp)

        if not author_match:
            continue

        # Try each title variant
        for variant in title_variants:
            if variant == cat_norm:
                return cat_work
            if len(cat_norm) >= 2 and len(variant) >= 2:
                if cat_norm in variant or variant in cat_norm:
                    return cat_work

    return None


# ── Work Number & Directory Assignment ────────────────────────────────────────

def get_next_work_number(db_path: str) -> int:
    """Get the next A-prefix work number."""
    con = duckdb.connect(db_path, read_only=True)
    result = con.execute(
        "SELECT MAX(CAST(SUBSTR(work_number, 2) AS INTEGER)) "
        "FROM works WHERE work_number LIKE 'A%' AND work_number NOT LIKE 'A%[a-z]'"
    ).fetchone()
    con.close()
    max_num = result[0] if result and result[0] else 0
    return max_num + 1


def get_next_directory_number(output_dir: str) -> int:
    """Get the next work_XXXX directory number."""
    max_num = 0
    base = Path(output_dir)
    if base.exists():
        for d in base.iterdir():
            if d.is_dir() and d.name.startswith("work_"):
                try:
                    num = int(d.name.replace("work_", ""))
                    max_num = max(max_num, num)
                except ValueError:
                    pass
    return max_num + 1


# ── JSON Generation ──────────────────────────────────────────────────────────

VOLUME_LETTERS = "abcdefghijklmnopqrstuvwxyz"


def generate_json(work: DetectedWork, work_number: str) -> Dict:
    """Generate pipeline-compatible raw JSON for a single work/volume."""
    chapters_json = []
    for ch in work.chapters:
        chapters_json.append({
            "title": ch.title,
            "content": ch.content,
        })

    return {
        "metadata": {
            "title": work.title_traditional,
            "creator": work.author_traditional,
            "language": "zh-Hant",
            "source": "Anna's Archive",
            "publisher": None,
        },
        "source": f"{work_number}.epub",
        "number_of_characters": work.character_count,
        "chapters": chapters_json,
    }


# ── Database Registration ────────────────────────────────────────────────────

def register_works(
    db_path: str,
    work_groups: List[WorkGroup],
    output_dir: str,
    dry_run: bool = False,
):
    """Register new works in the DuckDB catalog."""
    if dry_run:
        return

    con = duckdb.connect(db_path)

    # Get max IDs for manual assignment (DuckDB doesn't auto-increment)
    max_work_id = con.execute("SELECT COALESCE(MAX(work_id), 0) FROM works").fetchone()[0]
    max_file_id = con.execute("SELECT COALESCE(MAX(file_id), 0) FROM work_files").fetchone()[0]
    max_author_id = con.execute("SELECT COALESCE(MAX(author_id), 0) FROM authors").fetchone()[0]

    next_work_id = max_work_id + 1
    next_file_id = max_file_id + 1
    next_author_id = max_author_id + 1

    for group in work_groups:
        if group.is_duplicate:
            continue

        # Ensure author exists
        author_row = con.execute(
            "SELECT author_id FROM authors WHERE name_chinese = ?",
            [group.author_trad],
        ).fetchone()

        if not author_row:
            # Also check simplified
            author_row = con.execute(
                "SELECT author_id FROM authors WHERE name_chinese = ?",
                [group.author_simp],
            ).fetchone()

        if not author_row:
            con.execute(
                "INSERT INTO authors (author_id, name_chinese) VALUES (?, ?)",
                [next_author_id, group.author_trad],
            )
            logger.info(f"  Created author: {group.author_trad}")
            next_author_id += 1

        # Insert work
        work_id = next_work_id
        next_work_id += 1
        con.execute(
            """INSERT INTO works (work_id, work_number, title_chinese, author_chinese,
               directory_number, title_author, edition)
               VALUES (?, ?, ?, ?, ?, ?, 'annas_archive')""",
            [
                work_id,
                group.work_number,
                group.base_title_trad,
                group.author_trad,
                group.directory_number,
                f"{group.base_title_trad}_{group.author_trad}",
            ],
        )

        # Insert work_files for each volume
        for i, vol in enumerate(group.volumes):
            vol_letter = VOLUME_LETTERS[i] if len(group.volumes) > 1 else ""
            wn = f"{group.work_number}{vol_letter}"
            filename = f"{wn}_{vol.title_traditional}_{vol.author_traditional}.json"
            dir_name = f"work_{group.directory_number}"
            full_path = str(Path(output_dir) / dir_name / filename)

            con.execute(
                """INSERT INTO work_files (file_id, work_id, volume, filename, full_path,
                   directory_name, character_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [next_file_id, work_id, vol_letter, filename, full_path, dir_name, vol.character_count],
            )
            next_file_id += 1

    con.close()


# ── Author Extraction ────────────────────────────────────────────────────────

def extract_author_from_epub(book: epub.EpubBook, filename: str) -> str:
    """Extract author name (simplified) from EPUB metadata and filename."""
    # Try EPUB metadata first
    creators = book.get_metadata("DC", "creator")
    if creators:
        author = creators[0][0].strip()
        # Some have multiple authors separated by &
        if "&" in author:
            author = author.split("&")[0].strip()
        # Strip brackets
        author = re.sub(r"\[.*?\]", "", author).strip()
        if author and len(author) <= 10 and author != "zhanghenshui":
            return author

    # Extract from filename
    # Pattern: "... -- AUTHOR -- ..."
    m = re.search(r"--\s*(.+?)\s*--", filename)
    if m:
        author = m.group(1).strip()
        if "&" in author:
            author = author.split("&")[0].strip()
        author = re.sub(r"\[.*?\]", "", author).strip()
        if author and author != "zhanghenshui":
            return author

    # Special case for zhang henshui
    if "张恨水" in filename or "zhanghenshui" in filename.lower():
        return "张恨水"

    return ""


def extract_authors_from_epub(book: epub.EpubBook, filename: str) -> List[str]:
    """Extract all author names from multi-author collections."""
    authors = []

    # Check metadata
    creators = book.get_metadata("DC", "creator")
    if creators:
        for creator_tuple in creators:
            author = creator_tuple[0].strip()
            # Handle "Author1 & Author2 [Author1]" patterns
            author = re.sub(r"\[.*?\]", "", author).strip()
            for a in re.split(r"\s*[&,;，；]\s*", author):
                a = a.strip()
                if a and a != "zhanghenshui" and len(a) <= 10:
                    authors.append(a)

    # From filename
    m = re.search(r"--\s*(.+?)\s*--", filename)
    if m:
        raw = m.group(1).strip()
        raw = re.sub(r"\[.*?\]", "", raw).strip()
        for a in re.split(r"\s*[&,;，；]\s*", raw):
            a = a.strip()
            if a and a not in authors and len(a) <= 10:
                authors.append(a)

    # Special cases
    if not authors and ("张恨水" in filename or "zhanghenshui" in filename.lower()):
        authors.append("张恨水")

    return authors


# ── Main Processing ──────────────────────────────────────────────────────────

def process_epub(
    epub_path: Path,
    catalog_works: List[Dict],
    catalog_authors: Set[str],
    next_work_num: int,
    next_dir_num: int,
    output_dir: str,
    db_path: str,
    dry_run: bool = False,
) -> Tuple[IngestReport, int, int]:
    """Process a single EPUB collection file.

    Returns (report, updated_next_work_num, updated_next_dir_num).
    """
    filename = epub_path.name
    logger.info(f"\n{'='*70}")
    logger.info(f"Processing: {filename[:70]}")
    logger.info(f"{'='*70}")

    report = IngestReport(epub_file=filename, author="")

    try:
        book = epub.read_epub(str(epub_path))
    except Exception as e:
        report.errors.append(f"Failed to read EPUB: {e}")
        logger.error(f"  Failed to read EPUB: {e}")
        return report, next_work_num, next_dir_num

    # Detect author
    author_simp = extract_author_from_epub(book, filename)
    author_trad = S2T.convert(author_simp) if author_simp else ""
    report.author = f"{author_trad} ({author_simp})" if author_trad != author_simp else author_simp

    # Check for multi-author collection
    all_authors = extract_authors_from_epub(book, filename)
    is_multi_author = len(all_authors) > 1

    logger.info(f"  Author: {report.author}")
    if is_multi_author:
        logger.info(f"  Multi-author collection: {', '.join(all_authors)}")

    # Detect TOC structure
    toc_type = detect_toc_type(book)
    logger.info(f"  TOC type: {toc_type}")

    # Extract works based on TOC structure
    detected_works: List[DetectedWork] = []
    try:
        if toc_type == "hierarchical_works":
            detected_works = extract_works_hierarchical(book, author_simp)
        elif toc_type == "section_per_book":
            detected_works = extract_works_section_per_book(book, author_simp)
        elif toc_type == "flat_single_doc":
            detected_works = extract_works_flat_single_doc(book, author_simp)
        elif toc_type == "flat_interleaved":
            detected_works = extract_works_flat_interleaved(book, author_simp)
    except Exception as e:
        report.errors.append(f"Failed to extract works: {e}")
        logger.error(f"  Failed to extract works: {e}")
        import traceback
        traceback.print_exc()
        return report, next_work_num, next_dir_num

    # Set source on all works
    for w in detected_works:
        w.source_epub = filename

    report.works_detected = len(detected_works)
    logger.info(f"  Detected {len(detected_works)} works/volumes")

    if not detected_works:
        report.errors.append("No works detected")
        return report, next_work_num, next_dir_num

    # Group volumes
    work_groups = group_volumes(detected_works)
    logger.info(f"  Grouped into {len(work_groups)} logical works")

    # Match against catalog
    for group in work_groups:
        match = title_matches_catalog(
            group.base_title_trad, catalog_works, group.author_trad, group.author_simp
        )
        if not match:
            # Try simplified
            match = title_matches_catalog(
                group.base_title_simp, catalog_works, group.author_trad, group.author_simp
            )
        if match:
            group.is_duplicate = True
            group.matched_catalog_title = match.get("title_chinese", "")
            report.works_duplicate += 1
        else:
            report.works_new += 1

    logger.info(f"  New: {report.works_new}, Duplicates: {report.works_duplicate}")

    # Assign work numbers and directories
    for group in work_groups:
        if group.is_duplicate:
            continue

        group.work_number = f"A{next_work_num:03d}"
        group.directory_number = f"{next_dir_num:04d}"
        next_work_num += 1
        next_dir_num += 1

    # Log details
    for group in work_groups:
        total_chars = sum(v.character_count for v in group.volumes)
        total_chapters = sum(len(v.chapters) for v in group.volumes)
        status = "DUP" if group.is_duplicate else "NEW"
        vol_info = f" ({len(group.volumes)} vols)" if len(group.volumes) > 1 else ""

        detail = {
            "title_trad": group.base_title_trad,
            "title_simp": group.base_title_simp,
            "author": group.author_trad,
            "status": status,
            "volumes": len(group.volumes),
            "chapters": total_chapters,
            "characters": total_chars,
            "work_number": group.work_number,
            "directory": f"work_{group.directory_number}" if group.directory_number else "",
        }
        if group.is_duplicate:
            detail["matched"] = group.matched_catalog_title

        report.work_details.append(detail)
        logger.info(
            f"  [{status}] {group.base_title_trad}{vol_info} "
            f"- {total_chapters} ch, {total_chars:,} chars"
            + (f" (matched: {group.matched_catalog_title})" if group.is_duplicate else
               f" -> {group.work_number} work_{group.directory_number}")
        )

    # Write files and register
    if not dry_run:
        for group in work_groups:
            if group.is_duplicate:
                continue

            dir_name = f"work_{group.directory_number}"
            dir_path = Path(output_dir) / dir_name
            dir_path.mkdir(parents=True, exist_ok=True)

            for i, vol in enumerate(group.volumes):
                vol_letter = VOLUME_LETTERS[i] if len(group.volumes) > 1 else ""
                wn = f"{group.work_number}{vol_letter}"
                filename_json = f"{wn}_{vol.title_traditional}_{vol.author_traditional}.json"
                file_path = dir_path / filename_json

                data = generate_json(vol, wn)

                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                logger.info(f"  Wrote: {dir_name}/{filename_json}")
                report.works_written += 1

        # Register in database
        register_works(db_path, work_groups, output_dir, dry_run)
        logger.info(f"  Registered {report.works_new} new works in catalog")

    return report, next_work_num, next_dir_num


def main():
    parser = argparse.ArgumentParser(
        description="Ingest EPUB collections into translation pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run on all EPUBs
  python dev/admin/ingest_epub_collections.py --dry-run

  # Process a single EPUB
  python dev/admin/ingest_epub_collections.py --single "萧逸*.epub" --dry-run

  # Full ingestion
  python dev/admin/ingest_epub_collections.py
        """,
    )
    parser.add_argument(
        "--epub-dir", default=DEFAULT_EPUB_DIR,
        help="Directory containing EPUB files",
    )
    parser.add_argument(
        "--output-dir", default=DEFAULT_OUTPUT_DIR,
        help="Output directory for work_XXXX directories",
    )
    parser.add_argument(
        "--db-path", default=DEFAULT_DB_PATH,
        help="Path to works_translator.duckdb",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report only, no files written or DB changes",
    )
    parser.add_argument(
        "--single", metavar="PATTERN",
        help="Process only EPUBs matching this glob pattern",
    )
    parser.add_argument(
        "--report", metavar="PATH",
        help="Save JSON report to this path",
    )
    args = parser.parse_args()

    epub_dir = Path(args.epub_dir)
    if not epub_dir.exists():
        logger.error(f"EPUB directory not found: {epub_dir}")
        return 1

    # Find EPUB files
    epub_files = sorted(epub_dir.glob("*.epub"))
    if args.single:
        epub_files = [f for f in epub_files if fnmatch.fnmatch(f.name, args.single)]

    if not epub_files:
        logger.error(f"No EPUB files found in {epub_dir}" +
                      (f" matching '{args.single}'" if args.single else ""))
        return 1

    logger.info(f"Found {len(epub_files)} EPUB files to process")
    if args.dry_run:
        logger.info("DRY RUN — no files will be written")

    # Load catalog
    catalog_works, catalog_authors = load_catalog(args.db_path)
    logger.info(f"Catalog: {len(catalog_works)} works, {len(catalog_authors)} authors")

    # Get starting numbers
    next_work_num = get_next_work_number(args.db_path)
    next_dir_num = get_next_directory_number(args.output_dir)
    logger.info(f"Next work number: A{next_work_num:03d}")
    logger.info(f"Next directory: work_{next_dir_num:04d}")

    # Process each EPUB
    all_reports: List[IngestReport] = []
    for epub_path in epub_files:
        report, next_work_num, next_dir_num = process_epub(
            epub_path=epub_path,
            catalog_works=catalog_works,
            catalog_authors=catalog_authors,
            next_work_num=next_work_num,
            next_dir_num=next_dir_num,
            output_dir=args.output_dir,
            db_path=args.db_path,
            dry_run=args.dry_run,
        )
        all_reports.append(report)

    # Summary
    total_detected = sum(r.works_detected for r in all_reports)
    total_new = sum(r.works_new for r in all_reports)
    total_dup = sum(r.works_duplicate for r in all_reports)
    total_written = sum(r.works_written for r in all_reports)
    total_errors = sum(len(r.errors) for r in all_reports)

    logger.info(f"\n{'='*70}")
    logger.info(f"SUMMARY")
    logger.info(f"{'='*70}")
    logger.info(f"  EPUBs processed:  {len(all_reports)}")
    logger.info(f"  Works detected:   {total_detected}")
    logger.info(f"  New works:        {total_new}")
    logger.info(f"  Duplicates:       {total_dup}")
    if not args.dry_run:
        logger.info(f"  Files written:    {total_written}")
    logger.info(f"  Errors:           {total_errors}")

    for report in all_reports:
        if report.errors:
            logger.warning(f"  Errors in {report.epub_file[:50]}:")
            for err in report.errors:
                logger.warning(f"    - {err}")

    # Save report
    if args.report:
        report_data = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "dry_run": args.dry_run,
            "summary": {
                "epubs_processed": len(all_reports),
                "works_detected": total_detected,
                "works_new": total_new,
                "works_duplicate": total_dup,
                "works_written": total_written,
                "errors": total_errors,
            },
            "per_epub": [asdict(r) for r in all_reports],
        }
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        logger.info(f"\nReport saved to: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
