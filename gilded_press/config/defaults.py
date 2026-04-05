"""KDP specifications and defaults."""

from pathlib import Path

# Cover specs
KDP_COVER_WIDTH = 1600
KDP_COVER_HEIGHT = 2560
KDP_COVER_RATIO = 1.6  # height/width
KDP_COVER_MIN_WIDTH = 625
KDP_COVER_MIN_HEIGHT = 1000
KDP_COVER_MAX_DIM = 10000
KDP_COVER_MAX_SIZE_MB = 50
KDP_COVER_FORMAT = "JPEG"
KDP_COVER_COLOR_SPACE = "RGB"
KDP_COVER_DPI = 300
KDP_COVER_LIGHT_BG_BORDER_PX = 4
KDP_COVER_LIGHT_BG_BORDER_COLOR = (200, 200, 200)  # medium gray

# BISAC codes for classical Chinese fiction
BISAC_CODES = {
    "wuxia": "FIC009020",         # Fiction / Asian / Chinese
    "gong'an": "FIC009020",       # Fiction / Asian / Chinese
    "historical": "FIC014000",    # Fiction / Historical / General
    "classical": "FIC004000",     # Fiction / Classics
    "shenmo": "FIC009020",        # Fiction / Asian / Chinese
}

# Default keywords for Chinese literature
DEFAULT_KEYWORDS = [
    "Chinese literature",
    "classical Chinese novel",
    "translation",
    "wuxia",
]

# Catalog DB
DEFAULT_CATALOG_DB = Path.home() / "project_files" / "translation_project" / "db" / "works_translator.duckdb"

# Output
DEFAULT_OUTPUT_DIR = Path.home() / "project_files" / "translation_project" / "kdp_packages"
