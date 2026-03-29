"""Default configuration for Bronze Mirror strip OCR."""

from pathlib import Path

# OCR engine
# Use "ch" (not "chinese_cht") — the ch detection model (PP-OCRv4) is far superior
# to the multilingual detector used by chinese_cht. Simplified→traditional conversion
# is handled in post-processing via OpenCC.
DEFAULT_OCR_LANG = "ch"

# OCR post-processing
MIN_OCR_CONFIDENCE = 0.6  # Drop boxes below this confidence score
RUNNING_HEADER_MAX_CHARS = 20  # Max chars for a line to be considered a running header

# Page classification
MIN_BODY_CHARS = 20  # Pages with fewer chars are classified as blank

# Output paths
DEFAULT_OUTPUT_DIR = Path("/Users/jacki/project_files/translation_project/work_individual_files")
DEFAULT_STRIPS_BASE = Path(
    "/Users/jacki/project_files/translation_project/work_individual_files/ocr_strips"
)
