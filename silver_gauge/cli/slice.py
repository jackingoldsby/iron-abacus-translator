"""CLI for Silver Gauge column detection and strip slicing.

Usage:
    python -m silver_gauge.cli.slice --pdf /path/to/vol1.pdf --output-dir /path/to/strips/
    python -m silver_gauge.cli.slice --pdf /path/to/vol1.pdf --pages 80-97 --output-dir /path/to/strips/
    python -m silver_gauge.cli.slice --dir /path/to/三俠五義_俞平伯校點本/ --output-dir /path/to/strips/
    python -m silver_gauge.cli.slice --pdf /path/to/vol1.pdf --dry-run
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

import cv2

# Ensure silver_gauge is importable when run from inside the package
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from silver_gauge.config.defaults import (
    DEFAULT_DPI,
    DEFAULT_OUTPUT_BASE,
    MAX_COLUMN_WIDTH,
    MIN_COLUMN_WIDTH,
    SMOOTH_K,
    STRIP_PAD,
    THRESHOLD_PCT,
)
from silver_gauge.detectors.column_detector import (
    adaptive_detect,
    classify_strip,
    detect_columns,
    refine_strips,
    slice_columns,
    validate_columns,
)
from silver_gauge.extractors.image_preprocessor import preprocess
from silver_gauge.extractors.pdf_extractor import (
    discover_pdf_parts,
    extract_pages,
    get_page_count,
)


def _parse_page_range(s: str) -> tuple[int, int]:
    """Parse '80-97' into (80, 97) or '85' into (85, 85)."""
    if "-" in s:
        parts = s.split("-", 1)
        return int(parts[0]), int(parts[1])
    n = int(s)
    return n, n


def _slice_pdf(
    pdf_path: Path,
    output_dir: Path,
    page_range: tuple[int, int] | None,
    vol_label: str,
    dry_run: bool,
) -> dict:
    """Slice a single PDF into strips.

    Returns summary stats dict.
    """
    vol_dir = output_dir / vol_label

    with tempfile.TemporaryDirectory(prefix="silver_gauge_") as tmpdir:
        image_paths = extract_pages(
            pdf_path, dpi=DEFAULT_DPI, page_range=page_range, output_dir=Path(tmpdir)
        )
        start_page = page_range[0] if page_range else 0

        total_strips = 0
        total_degenerate = 0
        total_pages = len(image_paths)
        page_stats = []

        for i, img_path in enumerate(image_paths):
            page_num = start_page + i
            page_label = f"page_{page_num:04d}"

            # Preprocess (margin crop only)
            preprocess(img_path)

            # Load image for detection
            img = cv2.imread(str(img_path))
            if img is None:
                print(f"  WARNING: cannot read {img_path}")
                continue

            # Adaptive detection: try multiple param sets, pick best
            columns, best_params = adaptive_detect(img)
            # Refine: re-detect within overly wide strips to split merged columns
            pre_refine_count = len(columns)
            columns = refine_strips(img, columns)
            splits = len(columns) - pre_refine_count
            # Also run default to report raw/dropped stats
            raw_columns = detect_columns(img)
            _, dropped = validate_columns(raw_columns)

            # Per-page validation: always log detection results
            widths = [x_end - x_start for x_start, x_end in raw_columns]
            max_w = max(widths) if widths else 0
            adapted = best_params != {"smooth_k": SMOOTH_K, "threshold_pct": THRESHOLD_PCT}
            adapt_flag = f" [adapted: k={best_params['smooth_k']}, t={best_params['threshold_pct']}]" if adapted else ""
            split_flag = f" [split {splits} wide strips]" if splits > 0 else ""
            degenerate_flag = " *** DEGENERATE ***" if dropped > 0 else ""
            zero_flag = " *** ZERO STRIPS ***" if len(columns) == 0 and len(raw_columns) > 0 else ""
            print(f"  {page_label}: {len(columns)} strips "
                  f"(raw: {len(raw_columns)}, dropped: {dropped}, "
                  f"max_w: {max_w}px){adapt_flag}{split_flag}{degenerate_flag}{zero_flag}")

            if dry_run:
                page_stats.append({
                    "page_label": page_label,
                    "raw_detected": len(raw_columns),
                    "valid": len(columns),
                    "degenerate_dropped": dropped,
                    "max_column_width": max_w,
                })
                total_strips += len(columns)
                total_degenerate += dropped
                continue

            # Create page directory and save strips
            page_dir = vol_dir / page_label
            page_dir.mkdir(parents=True, exist_ok=True)

            # Save page image for Ivory Helm re-slicing
            cv2.imwrite(str(page_dir / "page_image.png"), img)

            strips = slice_columns(img, columns)
            strip_metadata = []

            for j, (strip_img, (x_start, x_end)) in enumerate(zip(strips, columns)):
                classification = classify_strip(strip_img)
                strip_file = f"strip_{j:03d}.png"
                cv2.imwrite(str(page_dir / strip_file), strip_img)

                strip_metadata.append({
                    "index": j,
                    "x_start": int(x_start),
                    "x_end": int(x_end),
                    "width": int(x_end - x_start),
                    "file": strip_file,
                    "classification": classification,
                })

            # Count text vs header_only
            text_count = sum(1 for s in strip_metadata if s["classification"] == "text")
            header_count = sum(1 for s in strip_metadata if s["classification"] == "header_only")
            if header_count > 0:
                print(f"    → {text_count} text, {header_count} header_only")

            # Write detection.json
            detection = {
                "page_label": page_label,
                "source_pdf": pdf_path.name,
                "page_num_in_pdf": page_num,
                "image_size": [int(img.shape[1]), int(img.shape[0])],
                "detection_params": {
                    "smooth_k": best_params["smooth_k"],
                    "threshold_pct": best_params["threshold_pct"],
                    "min_width": MIN_COLUMN_WIDTH,
                    "pad": STRIP_PAD,
                    "max_column_width": MAX_COLUMN_WIDTH,
                    "adapted": adapted,
                },
                "strips": strip_metadata,
                "degenerate_dropped": dropped,
                "total_detected": len(raw_columns),
            }
            with open(page_dir / "detection.json", "w", encoding="utf-8") as f:
                json.dump(detection, f, ensure_ascii=False, indent=2)

            total_strips += len(columns)
            total_degenerate += dropped

            if (i + 1) % 10 == 0:
                print(f"  ... {i + 1}/{total_pages} pages sliced")

    return {
        "pdf": pdf_path.name,
        "pages": total_pages,
        "strips": total_strips,
        "degenerate_dropped": total_degenerate,
        "page_stats": page_stats if dry_run else [],
    }


def cmd_slice(args: argparse.Namespace) -> None:
    """Main slice command."""
    dry_run = args.dry_run
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_BASE

    page_range = _parse_page_range(args.pages) if args.pages else None

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

    grand_total_strips = 0
    grand_total_pages = 0
    grand_total_degenerate = 0

    for vol_idx, pdf_path in enumerate(pdf_paths):
        vol_label = f"vol{vol_idx + 1}"
        page_count = get_page_count(pdf_path)
        print(f"Processing {pdf_path.name} ({page_count} pages) → {vol_label}/")

        stats = _slice_pdf(pdf_path, output_dir, page_range, vol_label, dry_run)
        grand_total_strips += stats["strips"]
        grand_total_pages += stats["pages"]
        grand_total_degenerate += stats["degenerate_dropped"]

        if dry_run and stats["page_stats"]:
            for ps in stats["page_stats"]:
                flag = " [DEGENERATE]" if ps["degenerate_dropped"] > 0 else ""
                print(f"  {ps['page_label']}: {ps['valid']} columns "
                      f"(raw: {ps['raw_detected']}, dropped: {ps['degenerate_dropped']}){flag}")

    # Write manifest.json (non-dry-run)
    if not dry_run:
        manifest = {
            "source_pdfs": [str(p) for p in pdf_paths],
            "total_pages": grand_total_pages,
            "total_strips": grand_total_strips,
            "degenerate_dropped": grand_total_degenerate,
            "detection_params": {
                "dpi": DEFAULT_DPI,
                "smooth_k": SMOOTH_K,
                "threshold_pct": THRESHOLD_PCT,
                "min_width": MIN_COLUMN_WIDTH,
                "pad": STRIP_PAD,
                "max_column_width": MAX_COLUMN_WIDTH,
            },
        }
        with open(output_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\nSummary: {grand_total_pages} pages → {grand_total_strips} strips "
          f"({grand_total_degenerate} degenerate dropped)")
    if not dry_run:
        print(f"Output: {output_dir}")


def main():
    parser = argparse.ArgumentParser(description="Silver Gauge — column detection & strip slicing")
    parser.add_argument("--pdf", help="Single PDF file")
    parser.add_argument("--dir", help="Directory of PDF parts")
    parser.add_argument("--pages", help="Page range, e.g. '80-97' or '85'")
    parser.add_argument("--output-dir", help="Output directory for strips")
    parser.add_argument("--dry-run", action="store_true", help="Show detection stats only")

    args = parser.parse_args()
    cmd_slice(args)


if __name__ == "__main__":
    main()
