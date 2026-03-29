"""Post-processing: reorder vertical columns, merge text, fix OCR errors."""

import re
import tempfile
from pathlib import Path

import cv2

from vermilion_brush.config.defaults import MIN_OCR_CONFIDENCE, RUNNING_HEADER_MAX_CHARS
from vermilion_brush.ocr.paddle_engine import OcrBox

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


def reorder_vertical_rtl(boxes: list[OcrBox]) -> list[list[OcrBox]]:
    """Group boxes into vertical columns and order right-to-left.

    For vertical Chinese text, columns run top-to-bottom and are read
    right-to-left across the page.

    Uses the column's running average center_x for assignment (not just the
    last box), which handles slight column drift in scanned pages.

    Returns:
        List of columns, each a list of OcrBox sorted top-to-bottom.
        Columns are ordered right-to-left.
    """
    if not boxes:
        return []

    # Sort all boxes by x-center
    sorted_boxes = sorted(boxes, key=lambda b: b.center_x)

    if len(sorted_boxes) < 2:
        return [sorted_boxes]

    # Use median width for threshold.
    widths = sorted(b.width for b in sorted_boxes)
    median_width = widths[len(widths) // 2]
    column_threshold = max(median_width * 0.7, 20)

    columns: list[list[OcrBox]] = []
    current_column: list[OcrBox] = [sorted_boxes[0]]
    column_cx_sum = sorted_boxes[0].center_x
    column_cx_count = 1

    for box in sorted_boxes[1:]:
        column_avg_cx = column_cx_sum / column_cx_count
        if abs(box.center_x - column_avg_cx) < column_threshold:
            current_column.append(box)
            column_cx_sum += box.center_x
            column_cx_count += 1
        else:
            columns.append(current_column)
            current_column = [box]
            column_cx_sum = box.center_x
            column_cx_count = 1
    columns.append(current_column)

    # Sort each column top-to-bottom
    for col in columns:
        col.sort(key=lambda b: b.top)

    # Reverse to get right-to-left reading order
    columns.reverse()

    return columns


def strip_running_headers(
    columns: list[list[OcrBox]], page_height: float | None = None
) -> list[list[OcrBox]]:
    """Remove running headers and footers from column data.

    Running headers/footers in the 三俠五義 scans are:
    - Short text at the very top or bottom of the page
    - Book title + chapter number (三俠五義第一回)
    - Page numbers (Chinese or Arabic numerals)
    """
    if not columns:
        return columns

    if page_height is None:
        all_boxes = [b for col in columns for b in col]
        if all_boxes:
            page_height = max(b.bottom for b in all_boxes)
        else:
            return columns

    # Header/footer zone: top/bottom 8% of content area
    header_cutoff = page_height * 0.08
    footer_cutoff = page_height * 0.92

    # Patterns that identify running headers
    header_patterns = re.compile(
        r"^(?:三[侠俠煲伙][五][義羲义]|"  # Title variants from OCR
        r"第.{1,6}回|"  # 第N回
        r"[\d一二三四五六七八九十百○]+)$"  # Page numbers
    )

    cleaned = []
    for col in columns:
        filtered = []
        for box in col:
            text = box.text.strip()
            in_header_zone = box.top < header_cutoff or box.top > footer_cutoff
            is_short = len(text) <= RUNNING_HEADER_MAX_CHARS
            if in_header_zone and is_short and header_patterns.match(text):
                continue
            filtered.append(box)
        if filtered:
            cleaned.append(filtered)

    return cleaned


def columns_to_text(columns: list[list[OcrBox]]) -> str:
    """Merge columns of OcrBox into a single reading-order text string.

    Each column's boxes are joined directly (no space — Chinese text).
    Columns are separated by newlines.
    """
    lines = []
    for col in columns:
        col_text = "".join(box.text for box in col)
        if col_text.strip():
            lines.append(col_text)
    return "\n".join(lines)


def fix_common_errors(text: str) -> str:
    """Fix common OCR misrecognitions in classical Chinese text.

    Handles:
    - Simplified → traditional conversion (via OpenCC)
    - Punctuation normalization (fullwidth/halfwidth)
    - Character confusions specific to 1920s typography
    - Stray artifacts
    """
    # Step 1: OpenCC simplified → traditional conversion.
    # This fixes the bulk of character issues: 见→見, 万→萬, 无→無, 业→業, etc.
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
    # These are NOT simplified/traditional issues — they're genuine misrecognitions
    # where the character shapes are similar in the old typeset.
    ocr_fixes = {
        # Variant/archaic forms
        "囘": "回",
        # Title-specific fixes (high confidence, seen repeatedly)
        "煲": "俠",  # 三煲五 → 三俠五
        "羲": "義",  # 五羲 → 五義
        # Middle dot → Chinese comma (used as separator in this OCR output)
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


def process_page_boxes(boxes: list[OcrBox]) -> str:
    """Full post-processing pipeline for a single page's OCR boxes.

    1. Filter out low-confidence detections
    2. Reorder vertical columns right-to-left
    3. Strip running headers/footers
    4. Merge columns to text
    5. Fix common OCR errors (including simplified→traditional)
    """
    boxes = filter_low_confidence(boxes)
    columns = reorder_vertical_rtl(boxes)
    columns = strip_running_headers(columns)
    text = columns_to_text(columns)
    text = fix_common_errors(text)
    return text


def process_page_strips(image_path: Path, engine) -> str:
    """OCR a page using strip slicing for improved accuracy on vertical text.

    Instead of running full-page OCR and reordering boxes afterward, this:
    1. Detects vertical columns via projection profile
    2. Slices image into individual column strips
    3. OCRs each strip independently (cleaner input → better accuracy)
    4. Merges text right-to-left (reading order), top-to-bottom within each strip
    5. Applies fix_common_errors (OpenCC s2t + OCR fixes)
    6. Strips running headers via regex

    Args:
        image_path: Path to preprocessed page image.
        engine: OcrEngine instance.

    Returns:
        Post-processed text for the page.
    """
    from vermilion_brush.extractors.column_detector import detect_columns, slice_columns

    img = cv2.imread(str(image_path))
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {image_path}")

    columns = detect_columns(img)
    if not columns:
        # Fallback: full-page OCR
        boxes = engine.recognize(image_path)
        return process_page_boxes(boxes)

    strips = slice_columns(img, columns)

    # OCR each strip independently
    lines = []
    with tempfile.TemporaryDirectory(prefix="vb_strip_") as tmpdir:
        for i, strip in enumerate(strips):
            strip_path = Path(tmpdir) / f"strip_{i:03d}.png"
            cv2.imwrite(str(strip_path), strip)
            boxes = engine.recognize(strip_path)
            boxes = filter_low_confidence(boxes)

            # Sort boxes top-to-bottom within the strip
            boxes.sort(key=lambda b: b.top)
            strip_text = "".join(b.text for b in boxes)
            if strip_text.strip():
                lines.append(strip_text)

    text = "\n".join(lines)
    text = fix_common_errors(text)

    # Strip running headers by regex (same patterns as strip_running_headers)
    header_re = re.compile(
        r"^(?:三[侠俠煲伙][五][義羲义]|"
        r"第.{1,6}回|"
        r"[\d一二三四五六七八九十百○]+)$"
    )
    cleaned_lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and not (len(stripped) <= RUNNING_HEADER_MAX_CHARS and header_re.match(stripped)):
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)
