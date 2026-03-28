#!/usr/bin/env python3
"""
Default configuration for Amber Inkstone.
"""

from pathlib import Path

# Database paths
DEFAULT_CATALOG_DB = Path("/Users/jacki/project_files/translation_project/db/works_translator.duckdb")
DEFAULT_PORTFOLIO_DB = Path("/Users/jacki/project_files/translation_project/db/artwork_portfolio.duckdb")

# Image cache
DEFAULT_CACHE_DIR = Path.home() / ".amber_inkstone" / "images"
THUMBNAIL_SIZE = (300, 300)

# Image validation
IMAGE_MIN_WIDTH = 600
IMAGE_MIN_HEIGHT = 800
IMAGE_MAX_ASPECT_RATIO = 2.0  # reject panoramic
MAX_DOWNLOAD_SIZE = 50 * 1024 * 1024  # 50 MB

# API settings
DEFAULT_TIMEOUT = 15
DEFAULT_LIMIT_PER_SOURCE = 10

# Image sources in priority order
IMAGE_SOURCES = [
    "wikimedia_commons",
    "met_museum",
]
