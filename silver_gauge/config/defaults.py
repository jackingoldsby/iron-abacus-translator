"""Default configuration for Silver Gauge column detection and strip slicing."""

from pathlib import Path

# PDF extraction
# 150 DPI is the sweet spot for PaddleOCR v2.7 on 1920s Chinese typography.
# Higher DPI (200, 250) introduces new errors because the model expects a certain
# character scale. Use 300 only for visual inspection / archival.
DEFAULT_DPI = 150
DEFAULT_IMAGE_FORMAT = "png"

# Image preprocessing
MARGIN_CROP_PERCENT = 0.02  # Crop 2% from each edge to remove yellowed borders

# Column detection
SMOOTH_K = 15  # Moving average kernel for projection smoothing
THRESHOLD_PCT = 0.15  # Threshold at 15% of max projection value
MIN_COLUMN_WIDTH = 30  # Minimum column width in pixels
STRIP_PAD = 15  # Pixels of padding on each side of a strip
MAX_COLUMN_WIDTH = 120  # Reject columns wider than this (degenerate detection guard)

# Strip classification
HEADER_STRIP_INK_PCT = 0.02  # <2% ink density → header-only strip

# Output paths
DEFAULT_OUTPUT_BASE = Path(
    "/Users/jacki/project_files/translation_project/work_individual_files/ocr_strips"
)

# Source data
DEFAULT_SOURCE_DIR = Path("/Users/jacki/project_files/translation_project/for_parsing")
