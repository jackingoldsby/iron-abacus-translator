"""Validate OCR accuracy on chapter 1 of 三俠五義 (pages 80-97).

Self-contained validation script that:
1. Calls silver_gauge to slice pages 80-97 → persistent strips
2. Calls bronze_mirror to OCR all strips
3. Compares against Wikisource ground truth
4. Outputs metrics + diff report

Usage:
    python bronze_mirror/scripts/validate_chapter1.py
    python bronze_mirror/scripts/validate_chapter1.py --resume   # skip slicing if strips exist
"""

import argparse
import difflib
import json
import sys
import time
from pathlib import Path

# Ensure imports work from workspace root
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

VALIDATION_DIR = Path(
    "/Users/jacki/project_files/translation_project/work_individual_files"
    "/ocr_strips/三俠五義_validation"
)
SOURCE_PDF = Path(
    "/Users/jacki/project_files/translation_project/for_parsing"
    "/三俠五義_俞平伯校點本/NTUL-9910002853F01_三俠五義_v.1.pdf"
)
GT_PATH = Path(
    "/Users/jacki/project_files/translation_project/for_parsing"
    "/三俠五義_俞平伯校點本/wikisource_chapter1.txt"
)
OUTPUT_DIR = Path("/tmp/ch1_ocr_validation")

PAGES = (80, 97)


def phase1_slice():
    """Slice pages 80-97 into persistent strips."""
    from silver_gauge.cli.slice import _slice_pdf

    print(f"=== Phase 1: Slicing pages {PAGES[0]}-{PAGES[1]} ===")
    print(f"Source: {SOURCE_PDF.name}")
    print(f"Output: {VALIDATION_DIR}")

    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    stats = _slice_pdf(
        pdf_path=SOURCE_PDF,
        output_dir=VALIDATION_DIR,
        page_range=PAGES,
        vol_label="vol1",
        dry_run=False,
    )
    elapsed = time.time() - t0

    print(f"Sliced {stats['pages']} pages → {stats['strips']} strips "
          f"({stats['degenerate_dropped']} degenerate) in {elapsed:.1f}s")


def phase2_ocr():
    """OCR all strips."""
    from bronze_mirror.ocr.paddle_engine import OcrEngine
    from bronze_mirror.readers.strip_reader import ocr_book, show_failures

    print(f"\n=== Phase 2: OCR strips ===")

    t0 = time.time()
    engine = OcrEngine()
    results = ocr_book(VALIDATION_DIR, engine, resume=True)
    elapsed = time.time() - t0

    total_chars = sum(len(text) for _, text in results)
    print(f"OCR'd {len(results)} pages → {total_chars} chars in {elapsed:.1f}s")

    # Show failures
    failures = show_failures(VALIDATION_DIR)
    if failures:
        print(f"\nFailed strips ({len(failures)}):")
        for f in failures:
            print(f"  {f['page_label']} / {f['strip_file']} — {f['status']}")
            print(f"    → {f['path']}")

    return results


def phase3_validate(results: list[tuple[str, str]]):
    """Compare OCR output against Wikisource ground truth."""
    print(f"\n=== Phase 3: Validation ===")

    # Merge all page texts
    ocr_text = "\n".join(text for _, text in results if text.strip())

    # Load ground truth
    if not GT_PATH.exists():
        print(f"Ground truth not found: {GT_PATH}")
        print("Skipping accuracy comparison. Run fetch_wikisource.py first.")
        # Still write output for manual inspection
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_DIR / "ocr_output.txt", "w", encoding="utf-8") as f:
            f.write(ocr_text)
        print(f"OCR output written to {OUTPUT_DIR / 'ocr_output.txt'}")
        return

    gt_text = GT_PATH.read_text(encoding="utf-8").strip()

    # Normalize both for comparison
    ocr_chars = ocr_text.replace("\n", "").replace(" ", "")
    gt_chars = gt_text.replace("\n", "").replace(" ", "")

    # Character-level accuracy
    matcher = difflib.SequenceMatcher(None, gt_chars, ocr_chars)
    accuracy = matcher.ratio() * 100

    # Count matching characters
    matching = sum(block.size for block in matcher.get_matching_blocks())

    # Write outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_DIR / "ocr_output.txt", "w", encoding="utf-8") as f:
        f.write(ocr_text)

    # Write diff report
    gt_lines = gt_text.splitlines()
    ocr_lines = ocr_text.splitlines()
    diff = difflib.unified_diff(gt_lines, ocr_lines, fromfile="ground_truth", tofile="ocr_output", lineterm="")
    diff_text = "\n".join(diff)
    with open(OUTPUT_DIR / "diff_report.txt", "w", encoding="utf-8") as f:
        f.write(diff_text)

    # Write metrics
    metrics = {
        "accuracy_pct": round(accuracy, 1),
        "gt_chars": len(gt_chars),
        "ocr_chars": len(ocr_chars),
        "matching_chars": matching,
        "missed_chars": len(gt_chars) - matching,
        "extra_chars": len(ocr_chars) - matching,
    }
    with open(OUTPUT_DIR / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print(f"\nAccuracy: {accuracy:.1f}%")
    print(f"  GT chars:       {len(gt_chars)}")
    print(f"  OCR chars:      {len(ocr_chars)}")
    print(f"  Matching:       {matching}")
    print(f"  Missed:         {len(gt_chars) - matching}")
    print(f"  Extra:          {len(ocr_chars) - matching}")
    print(f"\nOutputs in {OUTPUT_DIR}/")
    print(f"  ocr_output.txt   — full OCR text")
    print(f"  diff_report.txt  — unified diff vs ground truth")
    print(f"  metrics.json     — accuracy metrics")


def main():
    parser = argparse.ArgumentParser(description="Validate chapter 1 OCR accuracy")
    parser.add_argument("--resume", action="store_true", help="Skip slicing if strips exist")
    args = parser.parse_args()

    if args.resume and (VALIDATION_DIR / "vol1").exists():
        print("Resuming — skipping Phase 1 (strips already exist)")
    else:
        phase1_slice()

    results = phase2_ocr()
    phase3_validate(results)


if __name__ == "__main__":
    main()
