"""TOC structure detection for EPUB files."""

import re

from ebooklib import epub

# Pattern matching chapter headings in TOC leaf titles
_CHAPTER_TITLE_RE = re.compile(
    r"^(第[一二三四五六七八九十百零\d]+[回章節节]|楔子|尾聲|尾声|引子|序[章曲])"
)


def detect_toc_type(book: epub.EpubBook) -> str:
    """Detect the TOC structure type.

    Returns one of:
      'hierarchical_works'  — top sections are works (Huang Yi, Guzhengxia)
      'section_per_book'    — sections are books, children are chapters (Liang Yusheng, Wolong Sheng)
      'flat_chapters'       — all leaves are chapters of a single work (one chapter per file)
      'flat_single_doc'     — each leaf is an entire book in one HTML file (Xiao Yi, Wen Ruian)
      'flat_interleaved'    — flat leaves mixing book titles and chapters (Sima Ling, Liu Canyang)
    """
    toc = book.toc
    if not toc:
        return "flat_single_doc"

    sections = []
    leaves = []
    for item in toc:
        if isinstance(item, tuple):
            sections.append(item)
        else:
            leaves.append(item)

    # Pure sections at top level
    if sections and not leaves:
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

    # Pure leaves
    if not sections and leaves:
        unique_base_hrefs = set()
        for leaf in leaves:
            base = leaf.href.split("#")[0] if leaf.href else ""
            unique_base_hrefs.add(base)

        if len(unique_base_hrefs) < len(leaves) * 0.5:
            return "flat_interleaved"

        # Check if most leaves have chapter-like titles (第N回, 第N章, etc.)
        # If so, this is a single work with one chapter per file, not a collection
        chapter_count = sum(
            1 for leaf in leaves
            if leaf.title and _CHAPTER_TITLE_RE.match(leaf.title.strip())
        )
        if chapter_count >= len(leaves) * 0.6 and len(leaves) >= 3:
            return "flat_chapters"

        return "flat_single_doc"

    # Mixed sections and leaves
    if sections and leaves:
        return "hierarchical_works"

    return "flat_single_doc"


def is_generic_volume_title(title: str) -> bool:
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


def get_toc_leaves(toc_items) -> list:
    """Flatten TOC to leaf entries."""
    leaves = []
    for item in toc_items:
        if isinstance(item, tuple):
            leaves.extend(get_toc_leaves(item[1]))
        else:
            leaves.append(item)
    return leaves
