#!/usr/bin/env python3
"""
Cover page embedding and title page generation for EPUB.

Handles embedding a cover image into the EPUB structure
and generating the XHTML cover page.
"""

import logging
from pathlib import Path
from typing import Optional

from ebooklib import epub

logger = logging.getLogger(__name__)


def embed_cover(
    book: epub.EpubBook,
    image_path: Path,
) -> Optional[epub.EpubItem]:
    """Embed a cover image into the EPUB book.

    Args:
        book: The EpubBook being constructed
        image_path: Path to the cover image file (JPEG or PNG)

    Returns:
        The cover EpubItem if successful, None otherwise
    """
    if not image_path.exists():
        logger.warning(f"Cover image not found: {image_path}")
        return None

    suffix = image_path.suffix.lower()
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }.get(suffix)

    if not media_type:
        logger.warning(f"Unsupported cover image format: {suffix}")
        return None

    cover_data = image_path.read_bytes()
    book.set_cover(f"cover{suffix}", cover_data)
    logger.info(f"Embedded cover image: {image_path.name} ({len(cover_data) / 1024:.1f} KB)")

    return book.get_item_with_id("cover-img")
