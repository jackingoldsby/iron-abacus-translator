#!/usr/bin/env python3
"""
CLI wrapper for trivial footnote removal utility (Stage 6c).

Usage:
    python cli/remove_trivial_footnotes.py --input file.json
    python cli/remove_trivial_footnotes.py --input file.json --dry-run
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.remove_trivial_footnotes import main

if __name__ == "__main__":
    sys.exit(main())
