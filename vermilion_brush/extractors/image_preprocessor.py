"""Image preprocessing for OCR: crop margins only.

Benchmark results (2026-03-29, 三俠五義 pages 81-84):

  Engine comparison:
    PaddleOCR ch + OpenCC:  70-76% accuracy (BEST automated)
    macOS Vision API:       0% (can't detect vertical text in old scans)
    Tesseract chi_tra:      ~0% (garbage output)
    Preview.app Live Text:  ~90%+ (manual only, uses Apple Intelligence)

  Preprocessing comparison (PaddleOCR):
    raw (no preprocess):    76.3% (BEST — PaddleOCR does its own preprocessing)
    sharpen_gentle:         65-73% (inconsistent across runs)
    binarize:               48.2%
    deskew:                 HARMFUL (rotates vertical text pages)
    CLAHE:                  54.6%

  Key finding: PaddleOCR works best on raw images. External preprocessing
  (binarize, sharpen, CLAHE, deskew) consistently hurts accuracy.
  The only safe preprocessing is margin cropping.
"""

from pathlib import Path

import cv2
import numpy as np

from vermilion_brush.config.defaults import MARGIN_CROP_PERCENT


def preprocess(image_path: str | Path, output_path: str | Path | None = None) -> Path:
    """Preprocess a page image for OCR.

    Only crops margins — PaddleOCR handles all other preprocessing internally
    and performs worse on pre-processed images (benchmarked).

    Args:
        image_path: Path to the source image.
        output_path: Where to write the preprocessed image. Overwrites input if None.

    Returns:
        Path to the preprocessed image.
    """
    image_path = Path(image_path)
    if output_path is None:
        output_path = image_path
    else:
        output_path = Path(output_path)

    img = cv2.imread(str(image_path))
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {image_path}")

    # Crop margins (remove yellowed borders)
    h, w = img.shape[:2]
    margin_h = int(h * MARGIN_CROP_PERCENT)
    margin_w = int(w * MARGIN_CROP_PERCENT)
    cropped = img[margin_h : h - margin_h, margin_w : w - margin_w]

    cv2.imwrite(str(output_path), cropped)
    return output_path
