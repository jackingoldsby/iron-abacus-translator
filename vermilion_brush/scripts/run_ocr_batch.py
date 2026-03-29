#!/usr/bin/env python3
"""Batch OCR runner for Vermilion Brush — processes all PDFs sequentially.

Designed for headless deployment (e.g. Raspberry Pi). Processes one page at a time
to keep memory stable, with detailed logging for health monitoring.

Usage:
    python scripts/run_ocr_batch.py \
        --dir /path/to/三俠五義_俞平伯校點本/ \
        --output /path/to/raw_三俠五義.json \
        --log /path/to/ocr_job.log

    # Resume from where it left off (skips already-processed pages)
    python scripts/run_ocr_batch.py --dir ... --output ... --resume

    # Dry run — show page counts, no OCR
    python scripts/run_ocr_batch.py --dir ... --dry-run
"""

import argparse
import gc
import json
import logging
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

# Ensure vermilion_brush is importable
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root.parent) not in sys.path:
    sys.path.insert(0, str(_project_root.parent))

from vermilion_brush.config.defaults import DEFAULT_DPI
from vermilion_brush.extractors.image_preprocessor import preprocess
from vermilion_brush.extractors.pdf_extractor import (
    discover_pdf_parts,
    extract_pages,
    get_page_count,
)
from vermilion_brush.ocr.paddle_engine import OcrEngine
from vermilion_brush.ocr.postprocessor import process_page_boxes, process_page_strips
from vermilion_brush.structurers.hui_detector import detect_hui_boundaries
from vermilion_brush.structurers.json_emitter import PageData, emit_raw_json
from vermilion_brush.structurers.page_classifier import classify_page


def setup_logging(log_path: Path | None) -> logging.Logger:
    logger = logging.getLogger("vermilion_brush")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_path), encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


def load_checkpoint(checkpoint_path: Path) -> dict:
    if checkpoint_path.exists():
        return json.loads(checkpoint_path.read_text())
    return {"completed_pages": [], "page_data": []}


def save_checkpoint(checkpoint_path: Path, state: dict):
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Vermilion Brush batch OCR")
    parser.add_argument("--dir", required=True, help="Directory of PDF files")
    parser.add_argument("--output", help="Output JSON path")
    parser.add_argument("--log", help="Log file path")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help=f"DPI (default {DEFAULT_DPI})")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--dry-run", action="store_true", help="Show plan only")
    parser.add_argument("--mobile", action="store_true", help="Use mobile (lighter) OCR models")
    parser.add_argument("--strip", action="store_true", help="Use strip-slicing OCR (higher accuracy for vertical text)")
    args = parser.parse_args()

    # Paths
    pdf_dir = Path(args.dir)
    output_path = Path(args.output) if args.output else None
    log_path = Path(args.log) if args.log else (
        output_path.with_suffix(".log") if output_path else None
    )
    checkpoint_path = (
        output_path.with_suffix(".checkpoint.json") if output_path else Path("/tmp/vermilion_checkpoint.json")
    )

    logger = setup_logging(log_path)
    logger.info("=" * 70)
    logger.info("VERMILION BRUSH — Batch OCR Job")
    logger.info(f"Source: {pdf_dir}")
    logger.info(f"Output: {output_path}")
    logger.info(f"DPI: {args.dpi}")
    logger.info(f"Log: {log_path}")
    logger.info("=" * 70)

    # Discover PDFs
    pdf_paths = discover_pdf_parts(pdf_dir)
    if not pdf_paths:
        logger.error(f"No PDFs found in {pdf_dir}")
        sys.exit(1)

    # Build page plan: (pdf_path, page_num) for all pages across all PDFs
    page_plan = []
    for pdf_path in pdf_paths:
        count = get_page_count(pdf_path)
        logger.info(f"  {pdf_path.name}: {count} pages")
        for pg in range(count):
            page_plan.append((pdf_path, pg))

    total_pages = len(page_plan)
    logger.info(f"Total: {total_pages} pages across {len(pdf_paths)} PDFs")

    if args.dry_run:
        logger.info("DRY RUN — exiting")
        return

    if not output_path:
        logger.error("--output required for non-dry-run")
        sys.exit(1)

    # Load checkpoint for resume
    state = load_checkpoint(checkpoint_path) if args.resume else {"completed_pages": [], "page_data": []}
    completed_keys = set(state["completed_pages"])
    logger.info(f"Checkpoint: {len(completed_keys)} pages already done")

    # Init OCR engine (one-time model load)
    logger.info("Loading OCR engine...")
    t_engine = time.time()
    engine = OcrEngine(use_mobile=args.mobile)
    logger.info(f"Engine loaded in {time.time() - t_engine:.1f}s")

    # Process pages one at a time
    job_start = time.time()
    pages_done = len(completed_keys)
    errors = 0

    for i, (pdf_path, page_num) in enumerate(page_plan):
        page_key = f"{pdf_path.name}:{page_num}"

        if page_key in completed_keys:
            continue

        try:
            t0 = time.time()

            # Extract single page, preprocess (crop margins), then OCR
            with tempfile.TemporaryDirectory(prefix="vb_") as tmpdir:
                imgs = extract_pages(pdf_path, dpi=args.dpi, page_range=(page_num, page_num), output_dir=Path(tmpdir))
                preprocess(imgs[0])  # In-place margin crop

                if args.strip:
                    text = process_page_strips(imgs[0], engine)
                    box_count = 0  # Not tracked in strip mode
                else:
                    boxes = engine.recognize(imgs[0])
                    text = process_page_boxes(boxes)
                    box_count = len(boxes)
            total_count = get_page_count(pdf_path)
            page_type = classify_page(text, page_num, total_count)

            # Store result
            page_entry = {
                "text": text,
                "page_type": page_type.value,
                "source_pdf": pdf_path.name,
                "page_num_in_pdf": page_num,
                "global_page_index": i,
                "boxes": box_count,
                "chars": len(text),
            }
            state["page_data"].append(page_entry)
            state["completed_pages"].append(page_key)
            completed_keys.add(page_key)

            elapsed = time.time() - t0
            pages_done += 1

            # Progress + ETA
            elapsed_total = time.time() - job_start
            rate = pages_done / max(elapsed_total, 1) if pages_done > len(completed_keys) - len(state["completed_pages"]) + pages_done else None
            remaining = total_pages - len(completed_keys)
            eta_str = ""
            if rate and rate > 0 and remaining > 0:
                eta_seconds = remaining / rate
                eta = datetime.now() + timedelta(seconds=eta_seconds)
                eta_str = f" | ETA: {eta.strftime('%H:%M')} ({timedelta(seconds=int(eta_seconds))})"

            logger.info(
                f"[{len(completed_keys)}/{total_pages}] "
                f"{pdf_path.name} p{page_num:03d} | "
                f"{page_type.value:8s} | {box_count:2d} boxes | {len(text):4d} chars | "
                f"{elapsed:.1f}s{eta_str}"
            )

            # Checkpoint every 10 pages
            if len(completed_keys) % 10 == 0:
                save_checkpoint(checkpoint_path, state)

            # GC to keep memory stable
            gc.collect()

        except Exception as e:
            errors += 1
            logger.error(f"[{len(completed_keys)}/{total_pages}] FAILED {pdf_path.name} p{page_num}: {e}")
            # Don't crash — skip and continue
            state["completed_pages"].append(page_key)
            completed_keys.add(page_key)

    # Final checkpoint
    save_checkpoint(checkpoint_path, state)

    total_elapsed = time.time() - job_start
    logger.info("=" * 70)
    logger.info(f"OCR COMPLETE: {len(completed_keys)} pages in {timedelta(seconds=int(total_elapsed))}")
    logger.info(f"Errors: {errors}")

    # Build structured output
    logger.info("Detecting chapter boundaries...")
    page_texts = [p["text"] for p in state["page_data"]]
    hui_boundaries = detect_hui_boundaries(page_texts)
    logger.info(f"Detected {len(hui_boundaries)} 回 (hui) boundaries")

    for b in hui_boundaries:
        src = state["page_data"][b.page_index]
        logger.info(f"  {b.title} — {src['source_pdf']} p{src['page_num_in_pdf']}")

    # Convert to PageData objects for json_emitter
    from vermilion_brush.structurers.page_classifier import PageType
    page_data_objs = [
        PageData(
            text=p["text"],
            page_type=PageType(p["page_type"]),
            source_pdf=p["source_pdf"],
            page_num_in_pdf=p["page_num_in_pdf"],
            global_page_index=p["global_page_index"],
        )
        for p in state["page_data"]
    ]

    metadata = {
        "title": "三俠五義",
        "creator": "石玉昆",
        "language": "zh-Hant",
        "source": "OCR from 1925 亞東圖書館 俞平伯校點本",
        "publisher": "亞東圖書館",
    }

    result = emit_raw_json(page_data_objs, hui_boundaries, metadata)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info(f"Output: {output_path}")
    logger.info(f"  {len(result['chapters'])} chapters, {result['number_of_characters']} characters")
    logger.info("DONE")


if __name__ == "__main__":
    main()
