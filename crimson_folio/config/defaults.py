#!/usr/bin/env python3
"""
Default configuration for Crimson Folio.

Paths, theme settings, image search config.
"""

from pathlib import Path

# Default paths
DEFAULT_CSS_PATH = Path(__file__).parent.parent / "styles" / "kindle.css"
DEFAULT_CATALOG_DB = Path("/Users/jacki/project_files/translation_project/db/works_translator.duckdb")
DEFAULT_COVER_CACHE_DIR = Path.home() / ".crimson_folio" / "covers"

# Theme settings
AVAILABLE_THEMES = ["kindle", "modern", "minimal"]
DEFAULT_THEME = "kindle"

# Cover image settings
COVER_MIN_WIDTH = 600
COVER_MIN_HEIGHT = 800
COVER_OUTPUT_WIDTH = 1600
COVER_OUTPUT_HEIGHT = 2400
COVER_ASPECT_RATIO = 2 / 3  # Standard EPUB cover ratio

# Image search sources (in priority order)
IMAGE_SOURCES = [
    "wikimedia_commons",
    "met_museum",
]
