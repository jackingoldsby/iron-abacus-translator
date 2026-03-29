#!/usr/bin/env python3
"""Validate strip-slicing OCR on chapter 1 of 三俠五義 against Wikisource ground truth.

OCRs pages 80-97 from vol1 using strip slicing, then compares character-by-character
against the Wikisource digital text (6,226 chars).

Outputs to /tmp/ch1_ocr_validation/:
  - ocr_text.txt         — raw OCR output
  - ground_truth.txt     — Wikisource text
  - diff_report.txt      — character-level diff
  - metrics.json         — accuracy numbers

Usage:
    cd /Users/jacki/PycharmProjects/agentic_test_project
    python vermilion_brush/scripts/validate_chapter1.py
"""

import difflib
import json
import sys
import tempfile
import time
from pathlib import Path

# Ensure vermilion_brush is importable
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root.parent) not in sys.path:
    sys.path.insert(0, str(_project_root.parent))

from vermilion_brush.config.defaults import DEFAULT_DPI
from vermilion_brush.extractors.column_detector import detect_columns, slice_columns
from vermilion_brush.extractors.image_preprocessor import preprocess
from vermilion_brush.extractors.pdf_extractor import extract_pages
from vermilion_brush.ocr.paddle_engine import OcrEngine
from vermilion_brush.ocr.postprocessor import process_page_strips

# Paths
PDF_PATH = Path(
    "/Users/jacki/project_files/translation_project/for_parsing/"
    "三俠五義_俞平伯校點本/NTUL-9910002853F01_三俠五義_v.1.pdf"
)
GT_PATH = Path(
    "/Users/jacki/project_files/translation_project/work_individual_files/"
    "raw_三俠五義_wikisource.json"
)
OUTPUT_DIR = Path("/tmp/ch1_ocr_validation")

# Chapter 1 pages: 80 (title) through 97 (last body page)
PAGE_START = 80
PAGE_END = 97


def load_ground_truth() -> str:
    """Load Wikisource chapter 1 text, skipping the last block (wiki markup)."""
    with open(GT_PATH) as f:
        data = json.load(f)

    ch = data["chapters"][0]
    # Skip last block (wiki markup: </div>__NOEDITSECTION__...)
    blocks = ch["content"][:-1]
    text = "".join(b.get("content", "") for b in blocks)
    return text


def normalize_for_comparison(text: str) -> str:
    """Normalize text for fair comparison: strip whitespace, normalize punctuation."""
    # Remove all whitespace (spaces, newlines, tabs)
    result = "".join(text.split())
    return result


def compute_metrics(ocr_text: str, gt_text: str) -> dict:
    """Compute accuracy metrics between OCR output and ground truth."""
    matcher = difflib.SequenceMatcher(None, ocr_text, gt_text)
    ratio = matcher.ratio()

    # Count errors by opcode type
    substitutions = 0
    insertions = 0
    deletions = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            substitutions += max(i2 - i1, j2 - j1)
        elif tag == "insert":
            insertions += j2 - j1
        elif tag == "delete":
            deletions += i2 - i1

    # Character coverage: what % of GT chars appear in OCR
    gt_chars = set(gt_text)
    ocr_chars = set(ocr_text)
    coverage = len(gt_chars & ocr_chars) / len(gt_chars) if gt_chars else 0

    return {
        "sequence_matcher_ratio": round(ratio, 4),
        "character_coverage": round(coverage, 4),
        "ocr_chars": len(ocr_text),
        "gt_chars": len(gt_text),
        "substitutions": substitutions,
        "insertions": insertions,
        "deletions": deletions,
        "total_errors": substitutions + insertions + deletions,
    }


def generate_diff_report(ocr_text: str, gt_text: str, context: int = 10) -> str:
    """Generate a character-level diff report showing where OCR diverges from GT."""
    matcher = difflib.SequenceMatcher(None, ocr_text, gt_text)
    lines = []
    error_num = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        error_num += 1
        ocr_snippet = ocr_text[i1:i2]
        gt_snippet = gt_text[j1:j2]

        # Context: surrounding chars from GT
        ctx_before = gt_text[max(0, j1 - context) : j1]
        ctx_after = gt_text[j2 : j2 + context]

        lines.append(f"--- Error #{error_num} ({tag}) at GT pos {j1}-{j2} ---")
        lines.append(f"  Context: ...{ctx_before}[HERE]{ctx_after}...")
        if tag == "replace":
            lines.append(f"  OCR: {ocr_snippet}")
            lines.append(f"   GT: {gt_snippet}")
        elif tag == "insert":
            lines.append(f"  Missing in OCR: {gt_snippet}")
        elif tag == "delete":
            lines.append(f"  Extra in OCR: {ocr_snippet}")
        lines.append("")

    header = f"Character-level diff report: {error_num} error regions\n{'=' * 60}\n\n"
    return header + "\n".join(lines)


def main():
    print("=" * 60)
    print("VERMILION BRUSH — Chapter 1 Strip-Slicing Validation")
    print("=" * 60)

    # Check inputs exist
    if not PDF_PATH.exists():
        print(f"ERROR: PDF not found: {PDF_PATH}")
        sys.exit(1)
    if not GT_PATH.exists():
        print(f"ERROR: Ground truth not found: {GT_PATH}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load ground truth
    print("\nLoading Wikisource ground truth...")
    gt_raw = load_ground_truth()
    gt_normalized = normalize_for_comparison(gt_raw)
    print(f"  Ground truth: {len(gt_normalized)} chars (normalized)")

    # Init OCR engine
    print("\nLoading OCR engine...")
    t0 = time.time()
    engine = OcrEngine()
    print(f"  Engine loaded in {time.time() - t0:.1f}s")

    # Extract and OCR pages
    print(f"\nOCR'ing pages {PAGE_START}-{PAGE_END} with strip slicing...")
    all_page_texts = []
    job_start = time.time()

    with tempfile.TemporaryDirectory(prefix="vb_ch1_") as tmpdir:
        tmpdir = Path(tmpdir)

        for page_num in range(PAGE_START, PAGE_END + 1):
            t_page = time.time()

            # Extract single page
            imgs = extract_pages(PDF_PATH, dpi=DEFAULT_DPI, page_range=(page_num, page_num), output_dir=tmpdir)
            preprocess(imgs[0])  # Margin crop

            # Strip-slicing OCR
            text = process_page_strips(imgs[0], engine)

            elapsed = time.time() - t_page
            print(f"  Page {page_num:3d}: {len(text):4d} chars ({elapsed:.1f}s)")
            all_page_texts.append(text)

            # Clean up page image to save disk
            imgs[0].unlink(missing_ok=True)

    total_time = time.time() - job_start
    print(f"\nOCR complete: {len(all_page_texts)} pages in {total_time:.1f}s")

    # Merge all page texts
    ocr_raw = "\n".join(all_page_texts)
    ocr_normalized = normalize_for_comparison(ocr_raw)
    print(f"  OCR output: {len(ocr_normalized)} chars (normalized)")

    # Compute metrics
    print("\nComputing accuracy metrics...")
    metrics = compute_metrics(ocr_normalized, gt_normalized)
    metrics["pages"] = PAGE_END - PAGE_START + 1
    metrics["ocr_time_seconds"] = round(total_time, 1)

    print(f"\n{'=' * 60}")
    print(f"RESULTS")
    print(f"{'=' * 60}")
    print(f"  SequenceMatcher ratio:  {metrics['sequence_matcher_ratio']:.1%}")
    print(f"  Character coverage:     {metrics['character_coverage']:.1%}")
    print(f"  OCR chars:              {metrics['ocr_chars']}")
    print(f"  Ground truth chars:     {metrics['gt_chars']}")
    print(f"  Substitutions:          {metrics['substitutions']}")
    print(f"  Insertions:             {metrics['insertions']}")
    print(f"  Deletions:              {metrics['deletions']}")
    print(f"  Total errors:           {metrics['total_errors']}")
    print(f"  Time:                   {metrics['ocr_time_seconds']}s")

    # Generate diff report
    diff_report = generate_diff_report(ocr_normalized, gt_normalized)

    # Save outputs
    (OUTPUT_DIR / "ocr_text.txt").write_text(ocr_raw, encoding="utf-8")
    (OUTPUT_DIR / "ground_truth.txt").write_text(gt_raw, encoding="utf-8")
    (OUTPUT_DIR / "diff_report.txt").write_text(diff_report, encoding="utf-8")
    (OUTPUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\nOutputs saved to {OUTPUT_DIR}/")
    print(f"  ocr_text.txt       — raw OCR output")
    print(f"  ground_truth.txt   — Wikisource text")
    print(f"  diff_report.txt    — character-level diff ({metrics['total_errors']} errors)")
    print(f"  metrics.json       — accuracy numbers")


if __name__ == "__main__":
    main()
