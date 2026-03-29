"""Detect 回 (hui/chapter) boundaries from OCR text."""

import re
from dataclasses import dataclass


# Chinese numeral to int mapping
_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    "十": 10, "百": 100, "廿": 20, "卅": 30,
}


def _chinese_numeral_to_int(s: str) -> int:
    """Convert a Chinese numeral string to int.

    Handles: 一 through 一百二十 (covers 120回 of 三俠五義).
    """
    if not s:
        return 0

    total = 0
    current = 0

    for ch in s:
        val = _CN_DIGITS.get(ch, 0)
        if val == 100:
            total += (current or 1) * 100
            current = 0
        elif val == 10:
            total += (current or 1) * 10
            current = 0
        elif val >= 20 and ch in ("廿", "卅"):
            total += val
        else:
            current += val

    total += current
    return total


# Pattern for hui headers: 第N回 followed by the title
_HUI_PATTERN = re.compile(
    r"第([一二三四五六七八九十百零廿卅]+)回\s*([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+)"
)


@dataclass
class HuiBoundary:
    """A detected chapter (回) boundary."""

    hui_number: int
    title: str  # The full title text after 第N回
    page_index: int  # Index into the page list
    char_offset: int  # Character offset within the page text


def detect_hui_boundaries(
    page_texts: list[str],
) -> list[HuiBoundary]:
    """Detect hui (回) chapter boundaries across all pages.

    Args:
        page_texts: List of OCR text strings, one per page.

    Returns:
        List of HuiBoundary objects, sorted by hui number.
    """
    boundaries = []
    seen_numbers = set()

    for page_idx, text in enumerate(page_texts):
        for match in _HUI_PATTERN.finditer(text):
            num_str = match.group(1)
            title_text = match.group(2).strip()
            hui_num = _chinese_numeral_to_int(num_str)

            if hui_num <= 0 or hui_num > 200:
                continue

            # Skip duplicates (same hui found on TOC page and body page —
            # keep the body occurrence which comes later)
            if hui_num in seen_numbers:
                boundaries = [b for b in boundaries if b.hui_number != hui_num]

            seen_numbers.add(hui_num)
            boundaries.append(
                HuiBoundary(
                    hui_number=hui_num,
                    title=f"第{num_str}回 {title_text}",
                    page_index=page_idx,
                    char_offset=match.start(),
                )
            )

    boundaries.sort(key=lambda b: b.hui_number)
    return boundaries
