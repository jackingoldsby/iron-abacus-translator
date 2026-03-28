"""HTML content to block conversion for EPUB parsing."""

from typing import Dict, List

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup


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
    base_href = href.split("#")[0]
    item = book.get_item_with_href(base_href)
    if item is None:
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

    anchor = soup.find(id=fragment) or soup.find("a", attrs={"name": fragment})
    if not anchor:
        if fragment.startswith("filepos"):
            return html_to_blocks(html_content)
        return html_to_blocks(html_content)

    blocks = []
    # Include the anchor element itself if it has text
    anchor_text = anchor.get_text(strip=True)
    if anchor_text:
        blocks.append({"tag": anchor.name if anchor.name in ("h1", "h2", "h3", "h4", "p") else "p",
                        "content": anchor_text})

    # Walk siblings
    for sibling in anchor.find_next_siblings():
        if sibling.get("id", "").startswith("sigil_toc_id"):
            break
        text = sibling.get_text(strip=True)
        if text:
            tag = sibling.name if sibling.name in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote") else "p"
            blocks.append({"tag": tag, "content": text})

    return blocks


def build_spine_index(book: epub.EpubBook) -> List[str]:
    """Build ordered list of spine item hrefs (base, no fragment)."""
    spine_hrefs = []
    for idref, linear in book.spine:
        item = book.get_item_with_id(idref)
        if item:
            spine_hrefs.append(item.get_name())
    return spine_hrefs


def get_multi_file_content(book: epub.EpubBook, start_href: str, end_href: str,
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
