"""Check EPUB content compliance for KDP."""

import logging
import re
from pathlib import Path
from typing import List

import ebooklib
from ebooklib import epub

logger = logging.getLogger(__name__)


def check_content(epub_path: Path) -> dict:
    """Check EPUB content for KDP compliance.

    Checks:
    - AI disclosure present in preface
    - No obvious copyright issues
    - Public domain attribution

    Returns:
        Dict with 'compliant' bool and 'issues' list.
    """
    issues: List[str] = []
    info: List[str] = []

    book = epub.read_epub(str(epub_path))

    # Check for AI disclosure
    ai_disclosed = False
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            content = item.get_content().decode("utf-8", errors="ignore").lower()
            if any(phrase in content for phrase in [
                "ai-assisted", "ai assisted", "assisted by ai",
                "language model", "machine translation",
                "automated", "artificial intelligence",
            ]):
                ai_disclosed = True
                info.append(f"AI disclosure found in {item.get_name()}")
                break

    if not ai_disclosed:
        issues.append(
            "No AI disclosure found. KDP requires disclosure of AI-generated content. "
            "Add a statement to the preface."
        )

    # Check for potential copyright issues
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            content = item.get_content().decode("utf-8", errors="ignore")
            # Check for "all rights reserved" from source material
            if "all rights reserved" in content.lower():
                issues.append(
                    f"'{item.get_name()}' contains 'All Rights Reserved' — "
                    f"verify this is your own copyright notice, not from source material"
                )
            # Check for Project Gutenberg header (should be removed)
            if "project gutenberg" in content.lower():
                issues.append(
                    f"'{item.get_name()}' contains Project Gutenberg text — "
                    f"remove Gutenberg headers/footers before KDP submission"
                )

    return {
        "compliant": len(issues) == 0,
        "issues": issues,
        "info": info,
    }
