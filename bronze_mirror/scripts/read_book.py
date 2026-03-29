"""Batch OCR script — OCR all strips in a book directory.

Usage:
    python bronze_mirror/scripts/read_book.py \
        --strips-dir /path/to/ocr_strips/三俠五義/ \
        --output /path/to/raw_三俠五義.json

    python bronze_mirror/scripts/read_book.py \
        --strips-dir /path/to/ocr_strips/三俠五義/ \
        --output /path/to/raw.json --resume
"""

import sys
from pathlib import Path

# Ensure imports work from workspace root
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from bronze_mirror.cli.read import main

if __name__ == "__main__":
    main()
