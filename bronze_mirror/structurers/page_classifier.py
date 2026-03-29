"""Classify page types from OCR text."""

import re
from enum import Enum


class PageType(Enum):
    COVER = "cover"
    PREFACE = "preface"
    TOC = "toc"
    BODY = "body"
    BLANK = "blank"
    COLOPHON = "colophon"


def classify_page(text: str, page_num: int, total_pages: int) -> PageType:
    """Classify a page based on its OCR text content.

    Args:
        text: OCR text from the page.
        page_num: 0-indexed page number within the PDF.
        total_pages: Total number of pages in the PDF.

    Returns:
        PageType classification.
    """
    stripped = text.strip()

    # Blank pages: very little text
    if len(stripped) < 20:
        return PageType.BLANK

    # Cover: first few pages, short text, contains title-like content
    if page_num < 5 and len(stripped) < 200:
        if any(kw in stripped for kw in ("三俠五義", "俠義", "圖書館")):
            return PageType.COVER
        # Generic short early pages are likely covers/title pages
        if len(stripped) < 80:
            return PageType.COVER

    # Colophon: last few pages, publisher info
    if page_num > total_pages - 5 and len(stripped) < 300:
        if any(kw in stripped for kw in ("印刷", "發行", "出版", "版權", "圖書館")):
            return PageType.COLOPHON

    # Preface: contains preface markers
    preface_markers = ("序", "校讀後記", "前言", "自序", "弁言", "題記", "緒言")
    if page_num < 30:
        first_100 = stripped[:100]
        for marker in preface_markers:
            if marker in first_100:
                return PageType.PREFACE

    # TOC: multiple 第N回 patterns on one page
    hui_pattern = r"第[一二三四五六七八九十百零廿卅]+回"
    hui_matches = re.findall(hui_pattern, stripped)
    if len(hui_matches) >= 3:
        return PageType.TOC

    # Default: body text
    return PageType.BODY
