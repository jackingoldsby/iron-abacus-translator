#!/usr/bin/env python3
"""
CLI for EPUB Builder

Build EPUB files from translated JSON.

Usage:
    python cli/build_epub.py --input translated.json --output book.epub
    python cli/build_epub.py --input translated.json  # auto-names from metadata + catalog
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from processors.epub_builder import EpubBuilder


def main():
    parser = argparse.ArgumentParser(
        description="Build EPUB from translated JSON"
    )
    parser.add_argument("--input", "-i", required=True, help="Input translated JSON file")
    parser.add_argument("--output", "-o", help="Output EPUB file (default: auto from metadata)")
    parser.add_argument("--css", help="Custom CSS file (optional)")
    parser.add_argument("--catalog-db", help="Catalog DB path (default: from config)")

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {input_path} not found")
        return 1

    output_path = Path(args.output) if args.output else None
    css_path = Path(args.css) if args.css else None
    catalog_db = Path(args.catalog_db) if args.catalog_db else None

    builder = EpubBuilder(css_path=css_path, catalog_db=catalog_db)
    result = builder.build(input_path, output_path)
    size_kb = result.stat().st_size / 1024
    print(f"Generated: {result} ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    exit(main())
