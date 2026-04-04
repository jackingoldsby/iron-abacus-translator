"""Chapter boundary validation for scraped content."""

import re
import logging
from typing import List

from models.core import ScrapedChapter

logger = logging.getLogger(__name__)

# Patterns for chapter headings in classical Chinese novels
CHAPTER_PATTERNS = [
    re.compile(r"^第[一二三四五六七八九十百零〇○\d]+回"),
    re.compile(r"^第[一二三四五六七八九十百零〇○\d]+章"),
    re.compile(r"^第[一二三四五六七八九十百零〇○\d]+則"),
    re.compile(r"^第[一二三四五六七八九十百零〇○\d]+卷"),
    re.compile(r"^卷[一二三四五六七八九十百零〇○\d]+"),
]


def validate_chapters(chapters: List[ScrapedChapter]) -> List[str]:
    """Validate scraped chapters for completeness and consistency.

    Returns list of warning messages (empty = all good).
    """
    warnings = []

    if not chapters:
        warnings.append("No chapters found")
        return warnings

    # Check for empty chapters
    empty = [ch.title for ch in chapters if not ch.content]
    if empty:
        warnings.append(f"{len(empty)} empty chapters: {empty[:5]}")

    # Check for very short chapters (< 100 chars)
    short = [ch.title for ch in chapters if ch.character_count < 100 and ch.content]
    if short:
        warnings.append(f"{len(short)} very short chapters (<100 chars): {short[:5]}")

    # Check for numbering gaps
    numbers = []
    for ch in chapters:
        for pat in CHAPTER_PATTERNS:
            m = pat.match(ch.title)
            if m:
                num = _extract_number(ch.title)
                if num:
                    numbers.append(num)
                break

    if numbers:
        expected = set(range(min(numbers), max(numbers) + 1))
        missing = expected - set(numbers)
        if missing:
            warnings.append(f"Missing chapter numbers: {sorted(missing)}")

    return warnings


def _extract_number(title: str) -> int | None:
    """Extract the chapter number from a title string."""
    # Try Arabic numerals first
    m = re.search(r"(\d+)", title)
    if m:
        return int(m.group(1))

    # Try Chinese numerals
    cn = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
          "百": 100, "零": 0, "〇": 0, "○": 0}

    m = re.search(r"第([一二三四五六七八九十百零〇○]+)", title)
    if not m:
        return None

    s = m.group(1)
    result = 0
    current = 0
    for ch in s:
        val = cn.get(ch, 0)
        if val == 100:
            result += (current or 1) * 100
            current = 0
        elif val == 10:
            result += (current or 1) * 10
            current = 0
        else:
            current = val
    result += current
    return result if result > 0 else None
