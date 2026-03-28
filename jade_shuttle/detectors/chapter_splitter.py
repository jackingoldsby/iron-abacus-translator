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


def split_blocks_into_chapters(blocks: List[Dict], work_title: str) -> List[Chapter]:
    """Split a flat list of blocks into chapters by detecting heading patterns."""
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

    return chapters
