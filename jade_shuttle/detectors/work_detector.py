"""Work boundary detection — 4 strategies for different TOC structures."""

import logging
from typing import Dict, List, Tuple

from ebooklib import epub

from config.skip_patterns import is_chapter_title, is_separator_content, is_skip_title
from detectors.chapter_splitter import (
    extract_chapters_from_leaves,
    split_blocks_into_chapters,
)
from detectors.toc_detector import get_toc_leaves, is_generic_volume_title
from models.core import Chapter, DetectedWork
from transformers.encoding import S2T
from transformers.html_to_blocks import (
    build_spine_index,
    get_item_content,
    get_multi_file_content,
    html_to_blocks,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Spine-orphan detection and merging
# ---------------------------------------------------------------------------

def _merge_spine_orphans(
    book: epub.EpubBook,
    chapters: List[Chapter],
    toc_leaves: list,
) -> List[Chapter]:
    """Find spine files not covered by TOC leaves and merge into preceding chapters.

    After TOC-based extraction, some EPUB files may be in the spine (reading
    order) but not in the TOC. These are typically:
    - Section separator files (☆☆☆☆☆☆) with content after the separator
    - Multi-part chapters split across files
    - Orphaned content files

    This function finds those gaps and appends their content blocks to the
    preceding chapter.

    Args:
        book: The parsed EPUB book.
        chapters: Already-extracted chapters (modified in place).
        toc_leaves: The TOC leaf items used during extraction.

    Returns:
        The chapters list (same object, possibly with additional blocks).
    """
    if not chapters or not toc_leaves:
        return chapters

    spine_hrefs = build_spine_index(book)
    if not spine_hrefs:
        return chapters

    # Build set of hrefs covered by TOC leaves
    toc_hrefs = set()
    for leaf in toc_leaves:
        if hasattr(leaf, 'href') and leaf.href:
            toc_hrefs.add(leaf.href.split('#')[0])

    # Build ordered list of (toc_href, chapter_index) for mapping
    toc_href_to_chapter: Dict[str, int] = {}
    for i, leaf in enumerate(toc_leaves):
        if hasattr(leaf, 'href') and leaf.href:
            base = leaf.href.split('#')[0]
            if base not in toc_href_to_chapter and i < len(chapters):
                toc_href_to_chapter[base] = i

    # Scan spine for orphaned files
    total_merged = 0
    last_chapter_idx = -1

    for href in spine_hrefs:
        if href in toc_hrefs:
            # This spine item is covered by a TOC entry — update the "last chapter"
            if href in toc_href_to_chapter:
                last_chapter_idx = toc_href_to_chapter[href]
            continue

        # This spine item is NOT in the TOC — it's an orphan
        if last_chapter_idx < 0:
            continue  # orphan before any chapter — skip (likely cover/front matter)

        # Get the orphan's content
        content = get_item_content(book, href)
        if not content:
            continue

        blocks = html_to_blocks(content)
        if not blocks:
            continue

        # Strip leading separator lines (☆☆☆, ※※※, etc.)
        while blocks and is_separator_content(blocks[0].get("content", "")):
            blocks.pop(0)

        if not blocks:
            continue  # was only a separator, no real content

        # Check if content is substantial (>100 chars)
        total_chars = sum(len(b.get("content", "")) for b in blocks)
        if total_chars < 100:
            continue  # too small — probably a separator page or footer

        # Merge into the preceding chapter
        chapters[last_chapter_idx].content.extend(blocks)
        total_merged += 1
        logger.info(
            f"  Merged orphaned spine file '{href}' ({total_chars} chars, "
            f"{len(blocks)} blocks) into chapter {last_chapter_idx + 1}"
        )

    if total_merged:
        logger.info(f"  Total spine orphans merged: {total_merged}")

    return chapters


def _merge_separator_chapters(chapters: List[Chapter]) -> List[Chapter]:
    """Merge chapters whose title is a decorative separator into the preceding chapter.

    Some EPUBs have section dividers (☆☆☆☆☆☆, ※※※, etc.) as separate
    TOC entries. These aren't real chapters — their content belongs to
    the preceding chapter.
    """
    if len(chapters) <= 1:
        return chapters

    merged = []
    for ch in chapters:
        title = ch.title.strip() if ch.title else ""
        if merged and is_separator_content(title):
            # Strip separator lines from content, merge rest into preceding chapter
            content_blocks = [
                b for b in ch.content
                if not is_separator_content(b.get("content", ""))
            ]
            if content_blocks:
                merged[-1].content.extend(content_blocks)
                total_chars = sum(len(b.get("content", "")) for b in content_blocks)
                logger.info(
                    f"  Merged separator chapter '{title}' ({total_chars} chars, "
                    f"{len(content_blocks)} blocks) into '{merged[-1].title}'"
                )
        else:
            merged.append(ch)

    return merged


def _unwrap_single_child_sections(section_title: str, children: list) -> Tuple[str, list]:
    """Recursively unwrap sections that contain a single child section."""
    while True:
        sections = [c for c in children if isinstance(c, tuple)]
        leaves = [c for c in children if not isinstance(c, tuple)]

        if len(sections) == 1 and not leaves:
            child_sec, child_children = sections[0]
            section_title = child_sec.title.strip() if child_sec.title else section_title
            children = child_children
        else:
            break

    return section_title, children


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


def _extract_work_from_section(
    book: epub.EpubBook,
    work_title: str,
    children: list,
    author_simp: str,
    author_trad: str,
) -> List[DetectedWork]:
    """Extract works from a TOC section and its children."""
    results = []

    work_title, children = _unwrap_single_child_sections(work_title, children)
    has_subsections = any(isinstance(c, tuple) for c in children)

    if has_subsections:
        for child in children:
            if isinstance(child, tuple):
                vol_section, vol_children = child
                vol_title = vol_section.title.strip() if vol_section.title else work_title

                vol_title, vol_children = _unwrap_single_child_sections(vol_title, vol_children)

                if is_generic_volume_title(vol_title):
                    vol_title = f"{work_title}·{vol_title}"

                all_leaves = _collect_leaves_recursive(vol_children)
                chapters = extract_chapters_from_leaves(book, all_leaves)
                if chapters:
                    chapters = _merge_spine_orphans(book, chapters, all_leaves)
                    chapters = _merge_separator_chapters(chapters)
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
        chapter_leaves = [c for c in children if not isinstance(c, tuple)]
        chapters = extract_chapters_from_leaves(book, chapter_leaves)
        if chapters:
            chapters = _merge_spine_orphans(book, chapters, chapter_leaves)
            chapters = _merge_separator_chapters(chapters)
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


def extract_works_hierarchical(book: epub.EpubBook, author_simp: str) -> List[DetectedWork]:
    """Extract works from hierarchical TOC (e.g., Huang Yi, Guzhengxia).

    Structure: Section(work) > Section(volume) > Leaf(chapter)
    or: Section(work) > Leaf(chapter)
    """
    works = []
    author_trad = S2T.convert(author_simp)

    for item in book.toc:
        if not isinstance(item, tuple):
            continue
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
        if not work_title:
            continue
        # If section title is a skip title (目錄, 目录, etc.), use EPUB dc:title instead
        if is_skip_title(work_title):
            titles = book.get_metadata("DC", "title")
            work_title = titles[0][0].strip() if titles else ""
            if not work_title:
                continue

        chapter_leaves = []
        for child in children:
            if isinstance(child, tuple):
                _, nested = child
                chapter_leaves.extend([c for c in nested if not isinstance(c, tuple)])
            else:
                title = child.title.strip() if child.title else ""
                if not is_skip_title(title):
                    chapter_leaves.append(child)

        chapters = extract_chapters_from_leaves(book, chapter_leaves)
        if chapters:
            chapters = _merge_spine_orphans(book, chapters, chapter_leaves)
            chapters = _merge_separator_chapters(chapters)
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


def extract_works_flat_chapters(book: epub.EpubBook, author_simp: str) -> List[DetectedWork]:
    """Extract a single work where each TOC leaf = one chapter (one chapter per file).

    The work title is inferred from EPUB metadata (dc:title).
    All leaves are treated as chapters of that single work.
    """
    author_trad = S2T.convert(author_simp)

    # Get work title from EPUB metadata
    titles = book.get_metadata("DC", "title")
    work_title = titles[0][0].strip() if titles else ""
    if not work_title:
        work_title = "未知書名"

    leaves = [item for item in book.toc if not isinstance(item, tuple)]
    # Filter out skip titles (目錄, 版權信息, etc.)
    chapter_leaves = [l for l in leaves if l.title and not is_skip_title(l.title.strip())]

    chapters = extract_chapters_from_leaves(book, chapter_leaves)
    if not chapters:
        return []

    # Merge spine-orphaned content into preceding chapters
    chapters = _merge_spine_orphans(book, chapters, chapter_leaves)
    chapters = _merge_separator_chapters(chapters)

    title_trad = S2T.convert(work_title)
    detected = DetectedWork(
        title_simplified=work_title,
        title_traditional=title_trad,
        author_simplified=author_simp,
        author_traditional=author_trad,
        chapters=chapters,
    )
    detected.compute_character_count()
    return [detected]


def extract_works_flat_single_doc(book: epub.EpubBook, author_simp: str) -> List[DetectedWork]:
    """Extract works where each TOC leaf = an entire book (e.g., Wen Ruian, Xiao Yi)."""
    works = []
    author_trad = S2T.convert(author_simp)

    spine_hrefs = build_spine_index(book)
    leaves = [item for item in book.toc if not isinstance(item, tuple)]

    for i, leaf in enumerate(leaves):
        title = leaf.title.strip() if leaf.title else ""
        if not title or is_skip_title(title):
            continue

        next_href = leaves[i + 1].href if i + 1 < len(leaves) else None

        content = get_item_content(book, leaf.href)
        single_file_blocks = html_to_blocks(content) if content else []
        single_file_chars = sum(len(b.get("content", "")) for b in single_file_blocks)

        if single_file_chars > 5000:
            all_blocks = single_file_blocks
        else:
            all_blocks = get_multi_file_content(book, leaf.href, next_href, spine_hrefs)

        if not all_blocks:
            continue

        chapters = split_blocks_into_chapters(all_blocks, title)

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
    """Extract works from flat interleaved TOC (e.g., Sima Ling, Liu Canyang)."""
    works = []
    author_trad = S2T.convert(author_simp)

    leaves = get_toc_leaves(book.toc)

    current_work_title = None
    current_chapters: list = []

    def flush_work():
        nonlocal current_work_title, current_chapters
        if current_work_title and current_chapters:
            chapters = extract_chapters_from_leaves(book, current_chapters)
            if chapters:
                chapters = _merge_spine_orphans(book, chapters, current_chapters)
                chapters = _merge_separator_chapters(chapters)
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
            if current_work_title is None:
                current_work_title = title
            current_chapters.append(leaf)
        else:
            flush_work()
            current_work_title = title
            content = get_item_content(book, leaf.href)
            if content:
                blocks = html_to_blocks(content)
                total_chars = sum(len(b.get("content", "")) for b in blocks)
                if total_chars > 5000:
                    pass  # We'll collect the chapter leaves that follow

    flush_work()
    return works
