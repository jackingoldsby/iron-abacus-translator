"""HTML content to block conversion for Wikisource/ctext pages."""

import re
from typing import Dict, List

from bs4 import BeautifulSoup


def html_to_blocks(html: str) -> List[Dict]:
    """Convert MediaWiki HTML content to a list of tag/content blocks.

    Matches the Jade Shuttle output contract:
    [{"tag": "p", "content": "..."}, {"tag": "h3", "content": "..."}, ...]
    """
    soup = BeautifulSoup(html, "lxml")

    # Remove MediaWiki navigation/metadata elements
    for sel in soup.select(
        ".mw-parser-output > .noprint, "
        ".mw-editsection, "
        "#catlinks, "
        ".sister-wikipedia, "
        ".sistersitebox, "
        ".navigation-not-searchable, "
        "style, script, "
        ".mw-empty-elt, "
        "table.ambox, "
        "div.hatnote, "
        "sup.reference, "
        "#headerContainer, "
        "table"
    ):
        sel.decompose()

    # Find the parser output div (main content area)
    content = soup.find("div", class_="mw-parser-output")
    if not content:
        content = soup

    blocks = []
    for el in content.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "dd"]):
        # Skip nested elements (already captured by parent)
        if el.find_parent(["p", "blockquote", "dd"]):
            continue

        text = el.get_text(strip=True)
        if not text:
            continue

        # Skip MediaWiki boilerplate
        if _is_boilerplate(text):
            continue

        tag = el.name
        # Collapse div/dd to p for pipeline compatibility
        if tag in ("div", "dd"):
            tag = "p"

        blocks.append({"tag": tag, "content": text})

    # Split multi-paragraph blocks (some wikisource pages use <br> instead of <p>)
    blocks = _split_br_blocks(blocks)

    return blocks


def _is_boilerplate(text: str) -> bool:
    """Check if text is MediaWiki/Wikisource boilerplate to skip."""
    boilerplate = [
        "本作品在全世界都属于公有领域",
        "Public domain",
        "Wikisource",
        "维基文库",
        "維基文庫",
        "姊妹計劃",
        "此文档隶属于",
        "参见",
        "參見",
    ]
    for bp in boilerplate:
        if text.startswith(bp) or bp in text[:50]:
            return True
    return False


def _split_br_blocks(blocks: List[Dict]) -> List[Dict]:
    """Split blocks that contain newlines (from <br> tags) into separate blocks."""
    result = []
    for block in blocks:
        text = block["content"]
        if "\n" in text and len(text) > 100:
            for line in text.split("\n"):
                line = line.strip()
                if line:
                    result.append({"tag": block["tag"], "content": line})
        else:
            result.append(block)
    return result
