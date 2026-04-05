#!/usr/bin/env python3
"""
Gilded Press CLI — Prepare EPUB for KDP submission.

Usage:
    python -m cli.prepare --epub /path/to/book.epub
    python -m cli.prepare --epub /path/to/book.epub --cover /path/to/cover.jpg
    python -m cli.prepare --epub /path/to/book.epub --validate-only
"""

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.defaults import DEFAULT_OUTPUT_DIR
from converters.cover_converter import convert_cover, validate_cover
from converters.epub_validator import validate_epub
from converters.metadata_injector import generate_metadata, save_metadata, generate_description_html
from validators.content_checker import check_content

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Gilded Press (鍍金印) — Prepare EPUB for KDP submission",
    )
    parser.add_argument("--epub", required=True, type=Path, help="Input EPUB file")
    parser.add_argument("--cover", type=Path, help="Cover image (JPEG/PNG)")
    parser.add_argument("--back-cover", type=Path, help="Back cover image (for print)")
    parser.add_argument("--output", "-o", type=Path, help="Output directory")
    parser.add_argument("--genre", default="wuxia", help="Genre for BISAC code")
    parser.add_argument("--validate-only", action="store_true", help="Validate only, no conversion")
    parser.add_argument("--keywords", nargs="*", help="Additional keywords")

    args = parser.parse_args()

    if not args.epub.exists():
        logger.error(f"EPUB not found: {args.epub}")
        return 1

    # Output directory
    output_dir = args.output or DEFAULT_OUTPUT_DIR / args.epub.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Gilded Press — KDP Package Preparation")
    logger.info(f"  Input: {args.epub}")
    logger.info(f"  Output: {output_dir}")
    print()

    # === VALIDATE EPUB ===
    logger.info("=" * 50)
    logger.info("EPUB Validation")
    logger.info("=" * 50)
    epub_result = validate_epub(args.epub)
    for issue in epub_result["issues"]:
        logger.error(f"  ERROR: {issue}")
    for warning in epub_result["warnings"]:
        logger.warning(f"  WARN: {warning}")
    stats = epub_result.get("stats", {})
    logger.info(f"  Documents: {stats.get('documents', '?')}, "
                f"Size: {stats.get('total_size_kb', '?')} KB, "
                f"Footnotes: {stats.get('footnotes', '?')}, "
                f"TOC entries: {stats.get('toc_entries', '?')}")
    logger.info(f"  EPUB: {'PASS' if epub_result['valid'] else 'FAIL'}")
    print()

    # === CONTENT COMPLIANCE ===
    logger.info("=" * 50)
    logger.info("Content Compliance")
    logger.info("=" * 50)
    content_result = check_content(args.epub)
    for issue in content_result["issues"]:
        logger.error(f"  ERROR: {issue}")
    for info in content_result["info"]:
        logger.info(f"  OK: {info}")
    logger.info(f"  Content: {'PASS' if content_result['compliant'] else 'FAIL'}")
    print()

    # === COVER ===
    if args.cover:
        logger.info("=" * 50)
        logger.info("Cover Conversion")
        logger.info("=" * 50)
        cover_out = output_dir / "cover.jpg"
        convert_cover(args.cover, cover_out)
        cover_valid = validate_cover(cover_out)
        if not cover_valid["valid"]:
            for issue in cover_valid["issues"]:
                logger.error(f"  ERROR: {issue}")
        else:
            logger.info(f"  Cover: PASS")
        print()

    if args.validate_only:
        logger.info("Validation only — no package generated")
        all_pass = epub_result["valid"] and content_result["compliant"]
        return 0 if all_pass else 1

    # === METADATA ===
    logger.info("=" * 50)
    logger.info("Metadata Generation")
    logger.info("=" * 50)
    metadata = generate_metadata(
        args.epub, genre=args.genre, extra_keywords=args.keywords
    )
    save_metadata(metadata, output_dir / "metadata.json")

    # Description HTML
    desc_html = generate_description_html(metadata)
    desc_path = output_dir / "description.html"
    desc_path.write_text(desc_html, encoding="utf-8")
    logger.info(f"  Description: {desc_path}")
    print()

    # === COPY EPUB ===
    logger.info("=" * 50)
    logger.info("Package Assembly")
    logger.info("=" * 50)
    epub_out = output_dir / "manuscript.epub"
    shutil.copy2(args.epub, epub_out)
    logger.info(f"  Manuscript: {epub_out}")

    if args.back_cover and args.back_cover.exists():
        back_out = output_dir / "cover_back.jpg"
        shutil.copy2(args.back_cover, back_out)
        logger.info(f"  Back cover: {back_out}")

    # === SUMMARY ===
    print()
    logger.info("=" * 50)
    logger.info("KDP Package Ready")
    logger.info("=" * 50)
    logger.info(f"  Title: {metadata.get('title', '?')}")
    logger.info(f"  Author: {metadata.get('author', '?')}")
    logger.info(f"  BISAC: {metadata.get('bisac_code', '?')}")
    logger.info(f"  Keywords: {', '.join(metadata.get('keywords', []))}")
    logger.info(f"  AI Disclosure: Yes")
    logger.info(f"  Output: {output_dir}")
    print()

    # List output files
    for f in sorted(output_dir.iterdir()):
        size = f.stat().st_size / 1024
        logger.info(f"  {f.name}: {size:.0f} KB")

    return 0


if __name__ == "__main__":
    sys.exit(main())
