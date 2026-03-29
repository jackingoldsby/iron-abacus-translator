"""CLI for Vermilion Brush OCR pipeline.

Usage:
    python -m cli.ocr preview --pdf /path/to/vol1.pdf --pages 5-10
    python -m cli.ocr scan --pdf /path/to/vol1.pdf --output /tmp/output.json
    python -m cli.ocr scan --dir /path/to/三俠五義_俞平伯校點本/ --output /path/to/raw.json
    python -m cli.ocr scan --dir /path/to/ --dry-run
    python -m cli.ocr check --pdf /path/to/pdf --page 30
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

# Ensure vermilion_brush is importable when run from inside the package
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from vermilion_brush.config.defaults import DEFAULT_DPI, DEFAULT_OCR_WORKERS
from vermilion_brush.extractors.pdf_extractor import (
    discover_pdf_parts,
    extract_pages,
    get_page_count,
)
from vermilion_brush.extractors.image_preprocessor import preprocess
from vermilion_brush.ocr.paddle_engine import OcrEngine
from vermilion_brush.ocr.postprocessor import process_page_boxes
from vermilion_brush.structurers.hui_detector import detect_hui_boundaries
from vermilion_brush.structurers.json_emitter import PageData, emit_raw_json
from vermilion_brush.structurers.page_classifier import classify_page


def _parse_page_range(s: str) -> tuple[int, int]:
    """Parse '5-10' into (5, 10) or '5' into (5, 5)."""
    if "-" in s:
        parts = s.split("-", 1)
        return int(parts[0]), int(parts[1])
    n = int(s)
    return n, n


def _ocr_pages(
    pdf_path: Path,
    engine: OcrEngine,
    page_range: tuple[int, int] | None = None,
    preprocess_images: bool = True,
) -> list[tuple[str, int]]:
    """Extract and OCR pages from a single PDF.

    Returns:
        List of (text, page_num_in_pdf) tuples.
    """
    with tempfile.TemporaryDirectory(prefix="vermilion_") as tmpdir:
        image_paths = extract_pages(
            pdf_path, dpi=DEFAULT_DPI, page_range=page_range, output_dir=Path(tmpdir)
        )

        results = []
        start = page_range[0] if page_range else 0

        for i, img_path in enumerate(image_paths):
            page_num = start + i

            if preprocess_images:
                preprocess(img_path)

            boxes = engine.recognize(img_path)
            text = process_page_boxes(boxes)
            results.append((text, page_num))

        return results


def cmd_preview(args: argparse.Namespace) -> None:
    """Preview OCR results for a few pages."""
    pdf_path = Path(args.pdf)
    page_range = _parse_page_range(args.pages) if args.pages else (0, 4)

    print(f"Extracting pages {page_range[0]}-{page_range[1]} from {pdf_path.name}...")
    engine = OcrEngine()
    results = _ocr_pages(pdf_path, engine, page_range=page_range)

    for text, page_num in results:
        print(f"\n{'='*60}")
        print(f"PAGE {page_num}")
        print(f"{'='*60}")
        print(text)
        print(f"[{len(text)} chars]")


def cmd_check(args: argparse.Namespace) -> None:
    """OCR a single page and display results with source path for comparison."""
    pdf_path = Path(args.pdf)
    page_num = int(args.page)

    print(f"OCR check: {pdf_path.name} page {page_num}")
    print(f"Source: {pdf_path}")

    engine = OcrEngine()
    results = _ocr_pages(pdf_path, engine, page_range=(page_num, page_num))

    if results:
        text, _ = results[0]
        print(f"\n--- OCR Result ({len(text)} chars) ---")
        print(text)
        print(f"\nTo compare: open {pdf_path} at page {page_num + 1}")
    else:
        print("No text detected on this page.")


def cmd_scan(args: argparse.Namespace) -> None:
    """Full scan: OCR all pages, detect chapters, emit JSON."""
    dry_run = args.dry_run
    output_path = Path(args.output) if args.output else None

    # Collect PDFs
    if args.dir:
        pdf_paths = discover_pdf_parts(args.dir)
        if not pdf_paths:
            print(f"No PDFs found in {args.dir}")
            sys.exit(1)
        print(f"Found {len(pdf_paths)} PDF files")
    elif args.pdf:
        pdf_paths = [Path(args.pdf)]
    else:
        print("Provide --pdf or --dir")
        sys.exit(1)

    engine = OcrEngine()

    # OCR all pages across all PDFs
    all_pages: list[PageData] = []
    global_idx = 0

    for pdf_path in pdf_paths:
        page_count = get_page_count(pdf_path)
        print(f"Processing {pdf_path.name} ({page_count} pages)...")

        results = _ocr_pages(pdf_path, engine)

        for text, page_num in results:
            page_type = classify_page(text, page_num, page_count)
            all_pages.append(
                PageData(
                    text=text,
                    page_type=page_type,
                    source_pdf=pdf_path.name,
                    page_num_in_pdf=page_num,
                    global_page_index=global_idx,
                )
            )
            global_idx += 1

            if global_idx % 50 == 0:
                print(f"  ... {global_idx} pages processed")

    print(f"Total: {len(all_pages)} pages OCR'd")

    # Detect hui boundaries
    page_texts = [p.text for p in all_pages]
    hui_boundaries = detect_hui_boundaries(page_texts)
    print(f"Detected {len(hui_boundaries)} 回 (hui) boundaries")

    if dry_run:
        # Show classification summary and detected chapters
        from collections import Counter

        type_counts = Counter(p.page_type.value for p in all_pages)
        print(f"\nPage types: {dict(type_counts)}")
        print(f"\nDetected chapters:")
        for hui in hui_boundaries:
            src = all_pages[hui.page_index]
            print(f"  {hui.title}  (page {src.page_num_in_pdf} in {src.source_pdf})")
        return

    if not output_path:
        print("--output required for non-dry-run scan")
        sys.exit(1)

    # Emit JSON
    metadata = {
        "title": "三俠五義",
        "creator": "石玉昆",
        "language": "zh-Hant",
        "source": "OCR from 1925 亞東圖書館 俞平伯校點本",
        "publisher": "亞東圖書館",
    }

    result = emit_raw_json(all_pages, hui_boundaries, metadata)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nOutput: {output_path}")
    print(f"  {len(result['chapters'])} chapters")
    print(f"  {result['number_of_characters']} characters")


def main():
    parser = argparse.ArgumentParser(description="Vermilion Brush OCR pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # preview
    p_preview = subparsers.add_parser("preview", help="Preview OCR on a few pages")
    p_preview.add_argument("--pdf", required=True, help="Path to PDF file")
    p_preview.add_argument("--pages", help="Page range, e.g. '5-10' or '30'")

    # check
    p_check = subparsers.add_parser("check", help="OCR a single page for accuracy check")
    p_check.add_argument("--pdf", required=True, help="Path to PDF file")
    p_check.add_argument("--page", required=True, help="Page number (0-indexed)")

    # scan
    p_scan = subparsers.add_parser("scan", help="Full scan → JSON")
    p_scan.add_argument("--pdf", help="Single PDF file")
    p_scan.add_argument("--dir", help="Directory of PDF parts")
    p_scan.add_argument("--output", help="Output JSON path")
    p_scan.add_argument("--dry-run", action="store_true", help="Show detection only")

    args = parser.parse_args()

    if args.command == "preview":
        cmd_preview(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "scan":
        cmd_scan(args)


if __name__ == "__main__":
    main()
