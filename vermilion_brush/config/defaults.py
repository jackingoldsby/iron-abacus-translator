"""Default configuration for Vermilion Brush OCR pipeline."""

from pathlib import Path

# PDF extraction
# 150 DPI is the sweet spot for PaddleOCR v2.7 on 1920s Chinese typography.
# Higher DPI (200, 250) introduces new errors because the model expects a certain
# character scale. Use 300 only for visual inspection / archival.
DEFAULT_DPI = 150
DEFAULT_IMAGE_FORMAT = "png"

# OCR engine
# Use "ch" (not "chinese_cht") — the ch detection model (PP-OCRv4) is far superior
# to the multilingual detector used by chinese_cht. Simplified→traditional conversion
# is handled in post-processing via OpenCC.
DEFAULT_OCR_LANG = "ch"
DEFAULT_OCR_WORKERS = 4

# Image preprocessing
BINARIZE_BLOCK_SIZE = 31
BINARIZE_C = 10
DESKEW_ANGLE_THRESHOLD = 0.5  # degrees — skip deskew if angle < this
MARGIN_CROP_PERCENT = 0.02  # Crop 2% from each edge to remove yellowed borders

# OCR post-processing
MIN_OCR_CONFIDENCE = 0.6  # Drop boxes below this confidence score
RUNNING_HEADER_MAX_CHARS = 20  # Max chars for a line to be considered a running header

# Page classification
MIN_BODY_CHARS = 20  # Pages with fewer chars are classified as blank

# Output paths
DEFAULT_OUTPUT_DIR = Path("/Users/jacki/project_files/translation_project/work_individual_files")

# Source data
DEFAULT_SOURCE_DIR = Path("/Users/jacki/project_files/translation_project/for_parsing")
