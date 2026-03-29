"""Post-processing: fix OCR errors, simplified→traditional conversion, header stripping."""

import re

from bronze_mirror.config.defaults import MIN_OCR_CONFIDENCE, RUNNING_HEADER_MAX_CHARS
from bronze_mirror.ocr.paddle_engine import OcrBox

# Lazy-loaded OpenCC converter (simplified → traditional)
_s2t_converter = None


def _get_s2t_converter():
    """Lazy-load the OpenCC simplified→traditional converter."""
    global _s2t_converter
    if _s2t_converter is None:
        import opencc
        _s2t_converter = opencc.OpenCC("s2t")
    return _s2t_converter


def simplified_to_traditional(text: str) -> str:
    """Convert simplified Chinese characters to traditional using OpenCC.

    This is essential because PaddleOCR's `ch` model (which has the best detection)
    outputs simplified characters. The 1925 source text is traditional.
    """
    return _get_s2t_converter().convert(text)


def filter_low_confidence(boxes: list[OcrBox], threshold: float = MIN_OCR_CONFIDENCE) -> list[OcrBox]:
    """Drop boxes below the confidence threshold."""
    return [b for b in boxes if b.confidence >= threshold]


def fix_common_errors(text: str) -> str:
    """Fix common OCR misrecognitions in classical Chinese text.

    Handles:
    - Simplified → traditional conversion (via OpenCC)
    - Punctuation normalization (fullwidth/halfwidth)
    - Character confusions specific to 1920s typography
    - Stray artifacts
    """
    # Step 1: OpenCC simplified → traditional conversion.
    result = simplified_to_traditional(text)

    # Step 2: Normalize punctuation
    punct_replacements = {
        ",": "\uff0c",  # halfwidth comma → fullwidth
        ":": "\uff1a",
        ";": "\uff1b",
        "!": "\uff01",
        "?": "\uff1f",
        "(": "\uff08",
        ")": "\uff09",
    }
    for old, new in punct_replacements.items():
        result = re.sub(
            rf"(?<!\d){re.escape(old)}(?!\d)",
            new,
            result,
        )

    # Fullwidth period: only replace halfwidth . between CJK chars
    result = re.sub(
        r"(?<=[\u4e00-\u9fff])\.(?=[\u4e00-\u9fff])",
        "\u3002",
        result,
    )

    # Step 3: OCR shape confusions specific to 1920s classical Chinese typography.
    ocr_fixes = {
        "囘": "回",
        "煲": "俠",  # 三煲五 → 三俠五
        "羲": "義",  # 五羲 → 五義
        "·": "，",
    }
    for old, new in ocr_fixes.items():
        result = result.replace(old, new)

    # Remove isolated single ASCII characters between CJK (noise)
    result = re.sub(r"(?<=[\u4e00-\u9fff])[a-zA-Z](?=[\u4e00-\u9fff])", "", result)

    # Remove stray hashes/symbols between CJK
    result = re.sub(r"(?<=[\u4e00-\u9fff])[#＃]+(?=[\u4e00-\u9fff])", "", result)

    # Collapse multiple newlines
    result = re.sub(r"\n{3,}", "\n\n", result)

    return result


def strip_running_headers_regex(text: str, max_chars: int = RUNNING_HEADER_MAX_CHARS) -> str:
    """Strip running headers from merged text using regex patterns.

    Same patterns as the box-based strip_running_headers, but operates on
    already-merged text lines.
    """
    header_re = re.compile(
        r"^(?:三[侠俠煲伙][五][義羲义]|"
        r"第.{1,6}回|"
        r"[\d一二三四五六七八九十百○]+)$"
    )
    cleaned_lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and not (len(stripped) <= max_chars and header_re.match(stripped)):
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)
