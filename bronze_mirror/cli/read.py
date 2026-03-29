"""CLI for Bronze Mirror strip OCR.

Two-phase usage (with Platinum Scale validation between):
    # Phase 1: OCR all strips
    python -m bronze_mirror.cli.read ocr --strips-dir /path/to/strips/

    # (run platinum_scale.cli.validate here)

    # Phase 2: Merge validated results
    python -m bronze_mirror.cli.read merge --strips-dir /path/to/strips/ --output /path/to/raw.json

One-shot usage (no Platinum Scale):
    python -m bronze_mirror.cli.read run --strips-dir /path/to/strips/ --output /path/to/raw.json
    python -m bronze_mirror.cli.read run --strips-dir /path/to/strips/ --output /path/to/raw.json --resume

Other:
    python -m bronze_mirror.cli.read failures --strips-dir /path/to/strips/
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure bronze_mirror is importable when run from inside the package
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from bronze_mirror.ocr.paddle_engine import OcrEngine
from bronze_mirror.readers.strip_reader import (
    merge_book,
    ocr_book,
    ocr_book_phase1,
    show_failures,
)
from bronze_mirror.structurers.hui_detector import detect_hui_boundaries
from bronze_mirror.structurers.json_emitter import PageData, emit_raw_json
from bronze_mirror.structurers.page_classifier import classify_page


def _parse_page_range(s: str) -> tuple[int, int]:
    """Parse '80-97' into (80, 97) or '85' into (85, 85)."""
    if "-" in s:
        parts = s.split("-", 1)
        return int(parts[0]), int(parts[1])
    n = int(s)
    return n, n


def _read_manifest(strips_dir: Path) -> dict | None:
    manifest_path = strips_dir / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _emit_json(page_results: list[tuple[str, str]], strips_dir: Path, output_path: Path):
    """Build and write raw JSON from page results."""
    manifest = _read_manifest(strips_dir)
    page_texts = [text for _, text in page_results]
    total_pages = len(page_results)

    all_pages = []
    for i, (page_label, text) in enumerate(page_results):
        try:
            page_num = int(page_label.split("_")[1])
        except (IndexError, ValueError):
            page_num = i

        page_type = classify_page(text, page_num, total_pages)

        source_pdf = "unknown"
        if manifest and manifest.get("source_pdfs"):
            source_pdf = Path(manifest["source_pdfs"][0]).name

        all_pages.append(PageData(
            text=text,
            page_type=page_type,
            source_pdf=source_pdf,
            page_num_in_pdf=page_num,
            global_page_index=i,
        ))

    hui_boundaries = detect_hui_boundaries(page_texts)
    print(f"Detected {len(hui_boundaries)} 回 (hui) boundaries")

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


def cmd_ocr(args: argparse.Namespace) -> None:
    """Phase 1: OCR all strips (no merging)."""
    strips_dir = Path(args.strips_dir)
    page_filter = _parse_page_range(args.pages) if args.pages else None

    print("Loading OCR engine...")
    engine = OcrEngine()

    print(f"Phase 1: OCR strips in {strips_dir}")
    count = ocr_book_phase1(strips_dir, engine, resume=args.resume, page_filter=page_filter)
    print(f"OCR'd {count} pages")

    failures = show_failures(strips_dir)
    if failures:
        print(f"\nWARNING: {len(failures)} strips returned empty/missing")
        for f in failures[:10]:
            print(f"  {f['page_label']} / {f['strip_file']} — {f['status']}")


def cmd_merge(args: argparse.Namespace) -> None:
    """Phase 2: Merge OCR results (after Platinum Scale validation)."""
    strips_dir = Path(args.strips_dir)
    page_filter = _parse_page_range(args.pages) if args.pages else None

    print(f"Phase 2: Merging OCR results from {strips_dir}")
    page_results = merge_book(strips_dir, page_filter=page_filter)
    print(f"Merged {len(page_results)} pages")

    if args.output:
        _emit_json(page_results, strips_dir, Path(args.output))
    else:
        total_chars = sum(len(text) for _, text in page_results)
        print(f"Total: {total_chars} characters (use --output to emit JSON)")


def cmd_run(args: argparse.Namespace) -> None:
    """One-shot: OCR + merge (no Platinum Scale)."""
    strips_dir = Path(args.strips_dir)
    page_filter = _parse_page_range(args.pages) if args.pages else None

    print("Loading OCR engine...")
    engine = OcrEngine()

    print(f"OCR + merge: {strips_dir}")
    page_results = ocr_book(strips_dir, engine, resume=args.resume, page_filter=page_filter)
    print(f"Processed {len(page_results)} pages")

    failures = show_failures(strips_dir)
    if failures:
        print(f"\nWARNING: {len(failures)} strips returned empty/missing")

    if args.output:
        _emit_json(page_results, strips_dir, Path(args.output))
    else:
        total_chars = sum(len(text) for _, text in page_results)
        print(f"Total: {total_chars} characters (use --output to emit JSON)")


def cmd_failures(args: argparse.Namespace) -> None:
    """Show failed strips."""
    strips_dir = Path(args.strips_dir)
    failures = show_failures(strips_dir)
    if not failures:
        print("No failures found.")
    else:
        print(f"Found {len(failures)} failed strips:")
        for f in failures:
            print(f"  {f['page_label']} / {f['strip_file']} — {f['status']}")
            print(f"    Image: {f['path']}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Bronze Mirror — strip OCR & JSON emission")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Phase 1: OCR only
    p_ocr = subparsers.add_parser("ocr", help="Phase 1: OCR all strips (no merge)")
    p_ocr.add_argument("--strips-dir", required=True)
    p_ocr.add_argument("--pages", help="Page range filter, e.g. '80-97'")
    p_ocr.add_argument("--resume", action="store_true")

    # Phase 2: Merge only
    p_merge = subparsers.add_parser("merge", help="Phase 2: Merge OCR results into JSON")
    p_merge.add_argument("--strips-dir", required=True)
    p_merge.add_argument("--output", help="Output JSON path")
    p_merge.add_argument("--pages", help="Page range filter")

    # One-shot
    p_run = subparsers.add_parser("run", help="One-shot: OCR + merge (no Platinum Scale)")
    p_run.add_argument("--strips-dir", required=True)
    p_run.add_argument("--output", help="Output JSON path")
    p_run.add_argument("--pages", help="Page range filter")
    p_run.add_argument("--resume", action="store_true")

    # Failures
    p_fail = subparsers.add_parser("failures", help="Show failed strips")
    p_fail.add_argument("--strips-dir", required=True)

    args = parser.parse_args()

    if args.command == "ocr":
        cmd_ocr(args)
    elif args.command == "merge":
        cmd_merge(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "failures":
        cmd_failures(args)


if __name__ == "__main__":
    main()
