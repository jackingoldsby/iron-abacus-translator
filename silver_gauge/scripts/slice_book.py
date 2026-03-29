"""Batch slicing script — slice all PDFs in a directory into persistent strips.

Usage:
    python silver_gauge/scripts/slice_book.py \
        --dir /path/to/三俠五義_俞平伯校點本/ \
        --output-dir /path/to/ocr_strips/三俠五義/

    python silver_gauge/scripts/slice_book.py \
        --dir /path/to/三俠五義_俞平伯校點本/ \
        --dry-run
"""

import sys
from pathlib import Path

# Ensure imports work from workspace root
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from silver_gauge.cli.slice import main

if __name__ == "__main__":
    main()
