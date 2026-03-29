"""Detect vertical text columns via projection profile, validate, and slice into strips.

Strip-slicing approach: detect columns by projection profile, slice the image into
individual column strips, OCR each independently. This gives PaddleOCR cleaner input
than full-page OCR, improving accuracy from ~76% to ~91% on vertical Chinese text.

Key parameters (from benchmarking on 三俠五義 1925 scans):
- Smoothing kernel: k=15 (moving average)
- Threshold: 15% of max projection value
- Min column width: 30px
- Max column width: 120px (degenerate detection guard)
- Padding: 15px on each side of strip
"""

import numpy as np

import cv2

from silver_gauge.config.defaults import (
    HEADER_STRIP_INK_PCT,
    MAX_COLUMN_WIDTH,
    MIN_COLUMN_WIDTH,
    SMOOTH_K,
    STRIP_PAD,
    THRESHOLD_PCT,
)


def detect_columns(
    image: np.ndarray,
    min_width: int = MIN_COLUMN_WIDTH,
    smooth_k: int = SMOOTH_K,
    threshold_pct: float = THRESHOLD_PCT,
) -> list[tuple[int, int]]:
    """Detect vertical text columns via projection profile.

    Returns list of (x_start, x_end) tuples, sorted RIGHT-TO-LEFT (reading order).

    Algorithm:
    1. Binarize with Otsu threshold (inverted — text=white)
    2. Compute vertical projection profile (sum pixels per column)
    3. Smooth with moving average (k=smooth_k)
    4. Threshold at threshold_pct of max to find text regions
    5. Find contiguous regions > min_width pixels
    6. Sort right-to-left
    """
    # Convert to grayscale if needed
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image

    # Binarize with Otsu (inverted so text = white)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Vertical projection profile: sum of white pixels per column
    projection = np.sum(binary, axis=0).astype(float)

    # Smooth with moving average
    if smooth_k > 1 and len(projection) > smooth_k:
        kernel = np.ones(smooth_k) / smooth_k
        projection = np.convolve(projection, kernel, mode="same")

    # Threshold at percentage of max
    max_val = projection.max()
    if max_val == 0:
        return []
    threshold = max_val * threshold_pct

    # Find contiguous regions above threshold
    above = projection > threshold
    columns = []
    in_region = False
    start = 0

    for i, val in enumerate(above):
        if val and not in_region:
            start = i
            in_region = True
        elif not val and in_region:
            if i - start >= min_width:
                columns.append((start, i))
            in_region = False

    # Handle region that extends to the edge
    if in_region and len(above) - start >= min_width:
        columns.append((start, len(above)))

    # Sort right-to-left (descending x_start)
    columns.sort(key=lambda c: c[0], reverse=True)

    return columns


def validate_columns(
    columns: list[tuple[int, int]], max_width: int = MAX_COLUMN_WIDTH
) -> tuple[list[tuple[int, int]], int]:
    """Filter degenerate columns wider than max_width.

    Handles the page 97 problem: degenerate detection produces two huge
    "columns" spanning the whole page (1039px, 734px). These get dropped,
    and the page emits 0 strips — downstream classifies as blank.

    Args:
        columns: List of (x_start, x_end) from detect_columns().
        max_width: Maximum allowed column width in pixels.

    Returns:
        (valid_columns, dropped_count) — valid columns retain original order.
    """
    valid = []
    dropped = 0
    for x_start, x_end in columns:
        width = x_end - x_start
        if width <= max_width:
            valid.append((x_start, x_end))
        else:
            dropped += 1
    return valid, dropped


def slice_columns(
    image: np.ndarray, columns: list[tuple[int, int]], pad: int = STRIP_PAD
) -> list[np.ndarray]:
    """Slice image into individual column strips with padding.

    Args:
        image: Source image (BGR or grayscale).
        columns: List of (x_start, x_end) from detect_columns().
        pad: Pixels of padding on each side of the strip.

    Returns:
        List of column strip images, in the same order as input columns.
    """
    h = image.shape[0]
    w = image.shape[1]
    strips = []

    for x_start, x_end in columns:
        x0 = max(0, x_start - pad)
        x1 = min(w, x_end + pad)
        strip = image[0:h, x0:x1]
        strips.append(strip)

    return strips


# Expected column count range for typical body pages of vertical Chinese text.
# 三俠五義 at 150 DPI has ~10-13 columns per page. Pages outside this range
# likely have detection issues.
EXPECTED_COLUMNS_MIN = 8
EXPECTED_COLUMNS_MAX = 15


def _score_detection(columns: list[tuple[int, int]], max_width: int = MAX_COLUMN_WIDTH) -> float:
    """Score a detection result. Higher = better.

    Prefers:
    - More columns (within expected range)
    - Consistent column widths (low variance)
    - No degenerate columns
    """
    if not columns:
        return 0.0

    widths = [x_end - x_start for x_start, x_end in columns]
    n = len(columns)

    # Penalty for degenerate columns
    degenerate = sum(1 for w in widths if w > max_width)
    valid_widths = [w for w in widths if w <= max_width]
    valid_n = len(valid_widths)

    if valid_n == 0:
        return 0.0

    # Column count score: peaks in expected range
    if EXPECTED_COLUMNS_MIN <= valid_n <= EXPECTED_COLUMNS_MAX:
        count_score = valid_n  # More columns = more text captured
    elif valid_n < EXPECTED_COLUMNS_MIN:
        count_score = valid_n * 0.5  # Under-detecting, penalize
    else:
        count_score = EXPECTED_COLUMNS_MAX - (valid_n - EXPECTED_COLUMNS_MAX) * 0.3  # Over-detecting

    # Width consistency score: low std dev relative to mean
    mean_w = sum(valid_widths) / valid_n
    if mean_w > 0 and valid_n > 1:
        variance = sum((w - mean_w) ** 2 for w in valid_widths) / valid_n
        std_dev = variance ** 0.5
        consistency = max(0, 1.0 - std_dev / mean_w)
    else:
        consistency = 1.0

    # Degenerate penalty
    degen_penalty = degenerate * 5.0

    return count_score * consistency - degen_penalty


def adaptive_detect(
    image: np.ndarray, max_width: int = MAX_COLUMN_WIDTH
) -> tuple[list[tuple[int, int]], dict]:
    """Try multiple detection parameter sets and pick the best result.

    Iterates over smoothing kernels and thresholds to find parameters that
    produce the most plausible column layout for each page. This handles
    pages where the default parameters produce degenerate or too-few columns.

    Args:
        image: Page image (BGR or grayscale).
        max_width: Maximum allowed column width.

    Returns:
        (best_columns, best_params) — best validated columns and the
        parameters that produced them.
    """
    # Parameter grid: try reasonable variations
    smooth_values = [11, 15, 19]
    threshold_values = [0.10, 0.12, 0.15, 0.18, 0.20]

    best_score = -1.0
    best_columns = []
    best_params = {"smooth_k": SMOOTH_K, "threshold_pct": THRESHOLD_PCT}

    for sk in smooth_values:
        for tp in threshold_values:
            raw = detect_columns(image, smooth_k=sk, threshold_pct=tp)
            valid, _ = validate_columns(raw, max_width=max_width)
            score = _score_detection(raw, max_width=max_width)

            if score > best_score:
                best_score = score
                best_columns = valid
                best_params = {"smooth_k": sk, "threshold_pct": tp}

    return best_columns, best_params


def refine_strips(
    image: np.ndarray,
    columns: list[tuple[int, int]],
    max_width: int = MAX_COLUMN_WIDTH,
    min_width: int = MIN_COLUMN_WIDTH,
) -> list[tuple[int, int]]:
    """Refine strips by re-detecting within overly wide columns.

    If a detected column is wider than typical (> 1.5x median width) but
    still under max_width, it may contain two merged columns. Re-run
    detection on just that strip region with tighter parameters to try
    splitting it.

    Args:
        image: Full page image (BGR or grayscale).
        columns: Validated columns from detect_columns + validate_columns.
        max_width: Maximum column width threshold.
        min_width: Minimum column width threshold.

    Returns:
        Refined list of columns, possibly with wide columns split.
    """
    if len(columns) < 2:
        return columns

    widths = [x_end - x_start for x_start, x_end in columns]
    median_width = sorted(widths)[len(widths) // 2]
    wide_threshold = median_width * 1.8  # Columns >1.8x median are suspect

    refined = []
    for x_start, x_end in columns:
        width = x_end - x_start
        if width > wide_threshold and width > min_width * 2:
            # Extract the strip region and try re-detecting with tighter params
            h = image.shape[0]
            strip_region = image[0:h, x_start:x_end]
            sub_columns = detect_columns(
                strip_region, min_width=min_width, smooth_k=9, threshold_pct=0.20
            )
            sub_valid, _ = validate_columns(sub_columns, max_width=max_width)

            if len(sub_valid) >= 2:
                # Successfully split — offset sub-columns back to page coords
                for sx_start, sx_end in sub_valid:
                    refined.append((x_start + sx_start, x_start + sx_end))
            else:
                # Couldn't split further, keep original
                refined.append((x_start, x_end))
        else:
            refined.append((x_start, x_end))

    # Re-sort right-to-left
    refined.sort(key=lambda c: c[0], reverse=True)
    return refined


def classify_strip(strip_image: np.ndarray, ink_threshold: float = HEADER_STRIP_INK_PCT) -> str:
    """Classify strip as 'text' or 'header_only' by ink density ratio.

    A strip with very little ink (< ink_threshold of total pixels) is likely
    a running header/footer or margin decoration, not body text.

    Args:
        strip_image: Strip image (BGR or grayscale).
        ink_threshold: Fraction of pixels that must be ink (default 0.02 = 2%).

    Returns:
        'text' or 'header_only'.
    """
    if len(strip_image.shape) == 3:
        gray = cv2.cvtColor(strip_image, cv2.COLOR_BGR2GRAY)
    else:
        gray = strip_image

    # Binarize with Otsu (inverted — ink=white)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    ink_pixels = np.count_nonzero(binary)
    total_pixels = binary.shape[0] * binary.shape[1]

    if total_pixels == 0:
        return "header_only"

    ink_ratio = ink_pixels / total_pixels
    return "text" if ink_ratio >= ink_threshold else "header_only"
