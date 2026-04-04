"""Chapter splitting — extract chapters from TOC leaves or block lists."""

import re
from typing import Dict, List, Set

from ebooklib import epub

from models.core import Chapter
from transformers.html_to_blocks import (
    get_item_content,
    html_to_blocks,
    split_content_by_fragment,
)


def extract_chapters_from_leaves(book: epub.EpubBook, leaves: list) -> List[Chapter]:
    """Extract chapter content from TOC leaf items."""
    chapters = []
    seen_hrefs: Set[str] = set()

    for leaf in leaves:
        title = leaf.title.strip() if leaf.title else ""
        href = leaf.href if leaf.href else ""

        if not href:
            continue

        base_href = href.split("#")[0]
        fragment = href.split("#")[1] if "#" in href else ""

        content = get_item_content(book, href)
        if not content:
            continue

        if fragment and fragment not in ("chapter", ""):
            blocks = split_content_by_fragment(content, fragment)
        else:
            if base_href in seen_hrefs and not fragment:
                continue
            blocks = html_to_blocks(content)

        seen_hrefs.add(base_href)

        if blocks:
            ch_title = title
            if not ch_title and blocks and blocks[0].get("tag", "").startswith("h"):
                ch_title = blocks[0]["content"]
            chapters.append(Chapter(title=ch_title, content=blocks))

    return chapters


def _dedup_blocks(blocks: List[Dict]) -> List[Dict]:
    """Remove duplicate and container mega-blocks from nested HTML structures.

    Some EPUBs (e.g. Gutenberg) produce large blocks from parent container elements
    that duplicate content already present in their child elements. This removes:
    1. Exact duplicate large blocks (>1000 chars)
    2. Mega-blocks (>5000 chars) containing multiple chapter headings — these are
       parent containers whose content is already present in smaller blocks
    """
    heading_re = re.compile(
        r"第[一二三四五六七八九十百零\d]+[回章節节]"
    )
    seen: Set[str] = set()
    result = []
    for block in blocks:
        text = block.get("content", "").strip()
        # Remove exact duplicate large blocks
        if len(text) > 1000:
            if text in seen:
                continue
            seen.add(text)
        # Remove mega-blocks that contain multiple chapter headings — these are
        # parent container divs whose content is already in smaller child blocks
        if len(text) > 5000 and len(heading_re.findall(text)) > 1:
            continue
        result.append(block)
    return result


def _pre_split_blocks(blocks: List[Dict]) -> List[Dict]:
    """Pre-process blocks to split inline chapter headings into separate blocks.

    Some EPUBs (e.g. Project Gutenberg) embed chapter headings at the end of the
    previous chapter's last paragraph:  "...且聽下回分解。第三回　姬昌解圍進妲己"
    This splits such blocks so each heading becomes its own block.
    """
    heading_re = re.compile(
        r"(第[一二三四五六七八九十百零\d]+[回章節节][\s\u3000]+\S+)"
    )
    result = []
    for block in blocks:
        text = block.get("content", "").strip()
        tag = block.get("tag", "")
        # Find all heading positions in this block
        matches = list(heading_re.finditer(text))
        if not matches or (len(matches) == 1 and matches[0].start() == 0):
            # No inline headings, or block starts with a heading — keep as-is
            result.append(block)
            continue
        # Split at each heading position
        pos = 0
        for m in matches:
            if m.start() > pos:
                before = text[pos:m.start()].rstrip()
                if before:
                    result.append({"tag": tag, "content": before})
            pos = m.start()
        # Remainder after last match start
        if pos < len(text):
            result.append({"tag": tag, "content": text[pos:]})
    return result


def split_blocks_into_chapters(blocks: List[Dict], work_title: str) -> List[Chapter]:
    """Split a flat list of blocks into chapters by detecting heading patterns.

    Handles both standalone heading blocks and inline headings embedded at the end
    of the previous chapter's last paragraph (common in Gutenberg EPUBs).
    """
    blocks = _dedup_blocks(blocks)
    blocks = _pre_split_blocks(blocks)

    chapter_re = re.compile(
        r"^(第[一二三四五六七八九十百零\d]+[回章節节]|楔子|尾聲|尾声|引子|序[章曲])"
    )

    chapters = []
    current_title = work_title
    current_blocks: List[Dict] = []

    for block in blocks:
        text = block.get("content", "").strip()

        if chapter_re.match(text) or (block.get("tag", "").startswith("h") and len(text) < 60):
            if current_blocks:
                chapters.append(Chapter(title=current_title, content=current_blocks))
            current_title = text
            current_blocks = []
        else:
            current_blocks.append(block)

    if current_blocks:
        chapters.append(Chapter(title=current_title, content=current_blocks))

    # Merge consecutive chapters with the same 回/章 number (from split artifacts)
    hui_re = re.compile(r"^第([一二三四五六七八九十百零\d]+[回章節节])")
    merged = []
    for ch in chapters:
        m = hui_re.match(ch.title)
        if m and merged:
            prev_m = hui_re.match(merged[-1].title)
            if prev_m and prev_m.group(1) == m.group(1):
                # Same chapter number — merge content, keep shorter title
                shorter = ch.title if len(ch.title) < len(merged[-1].title) else merged[-1].title
                merged[-1] = Chapter(
                    title=shorter,
                    content=merged[-1].content + ch.content,
                )
                continue
        merged.append(ch)

    return merged
