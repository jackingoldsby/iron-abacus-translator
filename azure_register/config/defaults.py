#!/usr/bin/env python3
"""
Default configuration for Azure Register.

Paths, batch sizes, worker counts.
"""

import os
from pathlib import Path

# Database path resolution: explicit arg > env var > default
DEFAULT_DB_PATH = Path(
    os.getenv(
        "TRANSLATOR_DATA_ROOT",
        str(Path.home() / "project_files" / "translation_project"),
    )
) / "db" / "works_translator.duckdb"

# Library root for status.json sync
LIBRARY_ROOT = Path.home() / "project_files" / "translation_project" / "library"

# Batch sizes (works per API call)
LIBRARY_BATCH_SIZE = 15
READER_BATCH_SIZE = 10  # More tokens needed per work than factual enrichment

# Parallel API workers
DEFAULT_WORKERS = 50

# DeepSeek settings
DEFAULT_PROVIDER = "deepseek"
DEFAULT_MODEL = "deepseek-chat"
LIBRARY_TEMPERATURE = 0.2
READER_TEMPERATURE = 0.3
MAX_TOKENS = 8000
