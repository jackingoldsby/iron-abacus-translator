"""Detect vertical text columns via projection profile and slice into strips.

Strip-slicing approach: detect columns by projection profile, slice the image into
individual column strips, OCR each independently. This gives PaddleOCR cleaner input
than full-page OCR, improving accuracy from ~76% to ~91% on vertical Chinese text.

Key parameters (from benchmarking on 三俠五義 1925 scans):
- Smoothing kernel: k=15 (moving average)
- Threshold: 15% of max projection value
- Min column width: 30px
- Padding: 15px on each side of strip
"""

import numpy as np

import cv2


def detect_columns(
    image: np.ndarray, min_width: int = 30, smooth_k: int = 15, threshold_pct: float = 0.15
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


def slice_columns(
    image: np.ndarray, columns: list[tuple[int, int]], pad: int = 15
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
