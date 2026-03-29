"""Iterative orchestration loop: Silver Gauge → Bronze Mirror → Platinum Scale.

Pipelined processing:
- OCR runs sequentially (CPU-bound PaddleOCR)
- As each page finishes OCR, its strips are immediately queued for nano validation
- Nano validates strips from multiple pages concurrently (50 workers)
- Merge + assess happen as soon as validation completes per page

Failed pages are collected and re-sliced for the next round.

Products communicate ONLY through JSON files on disk. Ivory Helm imports
from the other products at function call time (not module level).

All parameters come from BookConfig — no hardcoded values.
"""

import asyncio
import json
import logging
import traceback
from datetime import datetime
from pathlib import Path

import cv2

from ivory_helm.config.book_config import BookConfig, load_config

logger = logging.getLogger(__name__)


def _load_env():
    """Load .env — search multiple locations for Mac/Pi portability."""
    from dotenv import load_dotenv

    root = Path(__file__).resolve().parents[2]
    for env_path in [
        root / ".env",
        root / "iron_abacus_translator" / ".env",
        Path.home() / ".env",
    ]:
        if env_path.exists():
            load_dotenv(env_path)
            return
    load_dotenv()  # fallback: search upward from cwd


def _preflight_check(strips_dir: Path) -> tuple:
    """Validate environment and data before starting. Returns (page_count, ocr_engine).

    Collects all errors, then raises one RuntimeError with all of them.
    """
    import os

    errors = []

    # 1. Check API key
    if not os.environ.get("OPENAI_API_KEY"):
        errors.append("OPENAI_API_KEY not set — check .env")

    # 2. Check PaddleOCR
    ocr_engine = None
    try:
        from bronze_mirror.ocr.paddle_engine import OcrEngine
        ocr_engine = OcrEngine()
    except Exception as e:
        errors.append(f"PaddleOCR init failed: {e}")

    # 3. Check strips_dir has page_* dirs
    vol_dirs = sorted(d for d in strips_dir.iterdir() if d.is_dir() and d.name.startswith("vol"))
    if not vol_dirs:
        vol_dirs = [strips_dir]

    page_count = 0
    for vol_dir in vol_dirs:
        page_count += sum(
            1 for d in vol_dir.iterdir()
            if d.is_dir() and d.name.startswith("page_")
        )

    if page_count == 0:
        errors.append(f"No page directories in {strips_dir}")
    else:
        # 4. Check first page has detection.json
        first_page = None
        for vol_dir in vol_dirs:
            pages = sorted(
                d for d in vol_dir.iterdir()
                if d.is_dir() and d.name.startswith("page_")
            )
            if pages:
                first_page = pages[0]
                break
        if first_page and not (first_page / "detection.json").exists():
            errors.append("No detection.json — did Silver Gauge run?")

    # 5. Check OpenAI reachable
    if not errors or not any("OPENAI_API_KEY" in e for e in errors):
        try:
            from openai import OpenAI
            client = OpenAI(timeout=10.0)
            client.models.list()
        except Exception as e:
            errors.append(f"OpenAI API unreachable: {e}")

    if errors:
        raise RuntimeError("Preflight failed:\n  - " + "\n  - ".join(errors))

    logger.info("Preflight OK: %d pages, PaddleOCR ready, OpenAI reachable", page_count)
    return page_count, ocr_engine


def _write_progress(strips_dir: Path, book_id: str | None, status: str,
                    round_num: int = 0, total_pages: int = 0,
                    passed: int = 0, pending: int = 0,
                    best_effort: int = 0, resumed: int = 0,
                    error: str | None = None) -> None:
    """Write progress.json to strips_dir root."""
    data = {
        "book_id": book_id or "unknown",
        "status": status,
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "round": round_num,
        "total_pages": total_pages,
        "passed": passed,
        "pending": pending,
        "best_effort": best_effort,
        "resumed": resumed,
    }
    if error:
        data["error"] = error
    with open(strips_dir / "progress.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _assess_page(page_dir: Path, cfg: BookConfig) -> dict:
    """Assess page quality from validation.json and ocr_strip results."""
    ih = cfg.ivory_helm

    validation_path = page_dir / "validation.json"
    if not validation_path.exists():
        return {"pass": False, "reason": "no_validation", "kept_ratio": 0,
                "total_chars": 0, "empty_strips": 0, "total_strips": 0}

    with open(validation_path, "r", encoding="utf-8") as f:
        val = json.load(f)

    total = val.get("validated", 0)
    kept = val.get("kept", 0)
    kept_ratio = kept / total if total > 0 else 0

    empty_count = 0
    for strip in val.get("strips", []):
        if strip.get("nano_classification") == "blank" and strip.get("status") != "pass_through":
            empty_count += 1

    merged_path = page_dir / "ocr_merged.json"
    total_chars = 0
    if merged_path.exists():
        with open(merged_path, "r", encoding="utf-8") as f:
            merged = json.load(f)
        total_chars = merged.get("total_chars", 0)

    passed = True
    reasons = []

    if kept_ratio < ih.min_kept_ratio and total > 0:
        passed = False
        reasons.append(f"kept_ratio={kept_ratio:.2f} < {ih.min_kept_ratio}")

    if total_chars < ih.min_chars_per_page:
        passed = False
        reasons.append(f"chars={total_chars} < {ih.min_chars_per_page}")

    if empty_count > ih.max_empty_strips:
        passed = False
        reasons.append(f"empty_strips={empty_count} > {ih.max_empty_strips}")

    return {
        "pass": passed,
        "reason": "; ".join(reasons) if reasons else "ok",
        "kept_ratio": round(kept_ratio, 3),
        "total_chars": total_chars,
        "empty_strips": empty_count,
        "total_strips": total,
    }


def _reslice_page(
    page_image_path: Path,
    page_dir: Path,
    strategy: dict,
    page_num: int,
    pdf_name: str,
    cfg: BookConfig,
) -> int:
    """Re-slice a single page with different detection parameters."""
    from silver_gauge.detectors.column_detector import (
        classify_strip,
        detect_columns,
        slice_columns,
        validate_columns,
    )

    sg = cfg.silver_gauge

    img = cv2.imread(str(page_image_path))
    if img is None:
        return 0

    for old_strip in page_dir.glob("strip_*.png"):
        old_strip.unlink()
    for old_ocr in page_dir.glob("ocr_strip_*.json"):
        old_ocr.unlink()
    for old_file in ("detection.json", "validation.json", "ocr_merged.json", "ocr_merged.txt"):
        p = page_dir / old_file
        if p.exists():
            p.unlink()

    smooth_k = strategy["smooth_k"]
    threshold_pct = strategy["threshold_pct"]

    raw_columns = detect_columns(
        img, min_width=sg.min_column_width, smooth_k=smooth_k, threshold_pct=threshold_pct,
    )
    columns, dropped = validate_columns(raw_columns, max_width=sg.max_column_width)
    strips = slice_columns(img, columns, pad=sg.strip_pad)

    strip_metadata = []
    for j, (strip_img, (x_start, x_end)) in enumerate(zip(strips, columns)):
        classification = classify_strip(strip_img, ink_threshold=sg.header_ink_pct)
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

    detection = {
        "page_label": page_dir.name,
        "source_pdf": pdf_name,
        "page_num_in_pdf": page_num,
        "image_size": [int(img.shape[1]), int(img.shape[0])],
        "detection_params": {
            "smooth_k": smooth_k,
            "threshold_pct": threshold_pct,
            "min_width": sg.min_column_width,
            "pad": sg.strip_pad,
            "max_column_width": sg.max_column_width,
            "iteration_strategy": strategy,
        },
        "strips": strip_metadata,
        "degenerate_dropped": dropped,
        "total_detected": len(raw_columns),
    }
    with open(page_dir / "detection.json", "w", encoding="utf-8") as f:
        json.dump(detection, f, ensure_ascii=False, indent=2)

    return len(columns)


def _write_report(job: dict) -> None:
    """Write iteration_report.json to disk."""
    report_path = job["page_dir"] / "iteration_report.json"
    report = {
        "page_label": job["page_dir"].name,
        "page_num": job["page_num"],
        "book_id": job["book_id"],
        "iterations": job["iterations"],
        "final_status": job["final_status"],
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


async def _validate_merge_assess(
    job: dict,
    nano_client,
    nano_semaphore: asyncio.Semaphore,
    cfg: BookConfig,
    validate_page,
    merge_page,
) -> None:
    """Validate, merge, and assess a single page. Sets job['_round_passed']."""
    val_summary = await validate_page(job["page_dir"], nano_client, nano_semaphore)
    job["iterations"][-1]["kept"] = val_summary.get("kept", 0)
    job["iterations"][-1]["excluded"] = val_summary.get("excluded", 0)

    merge_page(job["page_dir"])

    assessment = _assess_page(job["page_dir"], cfg)
    job["iterations"][-1]["assessment"] = assessment
    job["_round_passed"] = assessment["pass"]


async def _run_pipeline_round(
    pending: list[dict],
    round_num: int,
    ocr_engine,
    nano_client,
    nano_semaphore: asyncio.Semaphore,
    cfg: BookConfig,
) -> tuple[list[dict], list[dict]]:
    """Run one pipelined round: OCR feeds validation as pages complete.

    OCR is sequential (CPU-bound). As each page finishes OCR, a validation
    task is spawned immediately. Nano's 50-worker semaphore controls
    concurrency across all in-flight validation tasks.

    Returns:
        (passed_jobs, failed_jobs)
    """
    from bronze_mirror.readers.strip_reader import merge_page, ocr_strips_only
    from platinum_scale.validators.strip_validator import validate_page

    round_label = f"Round {round_num + 1}"
    logger.info("%s: pipelining %d pages (OCR → validate → merge → assess)",
               round_label, len(pending))

    # As OCR completes each page, fire off its validation immediately.
    # Validation tasks run concurrently while OCR continues on the next page.
    validation_tasks: list[asyncio.Task] = []

    for i, job in enumerate(pending):
        # OCR this page in a thread so the event loop stays free for validation
        iter_info = {"iteration": round_num + 1}
        ocr_results = await asyncio.to_thread(ocr_strips_only, job["page_dir"], ocr_engine)
        iter_info["ocr_strips"] = len(ocr_results)
        iter_info["ocr_ok"] = sum(1 for r in ocr_results if r.get("status") == "ok")
        iter_info["ocr_empty"] = sum(1 for r in ocr_results if r.get("status") == "empty")
        job["iterations"].append(iter_info)

        # Immediately queue validation — runs concurrently while OCR continues
        task = asyncio.create_task(
            _validate_merge_assess(
                job, nano_client, nano_semaphore, cfg, validate_page, merge_page,
            ),
            name=f"validate_{job['page_dir'].name}",
        )
        validation_tasks.append(task)

        if (i + 1) % 50 == 0:
            logger.info("  OCR: %d/%d pages (validation running in parallel)",
                       i + 1, len(pending))

    logger.info("  OCR complete for %d pages — waiting for remaining validation", len(pending))

    # Wait for all validation tasks to complete
    await asyncio.gather(*validation_tasks)

    # Split into passed vs failed
    passed = []
    failed = []
    for job in pending:
        if job.get("_round_passed"):
            job["final_status"] = "pass"
            _write_report(job)
            passed.append(job)
        else:
            failed.append(job)

    logger.info("%s result: %d passed, %d failed", round_label, len(passed), len(failed))
    return passed, failed


async def process_book(
    strips_dir: Path,
    source_images_dir: Path | None = None,
    resume: bool = True,
    book_id: str | None = None,
) -> list[dict]:
    """Process all pages through pipelined iteration rounds.

    Each round pipelines OCR → validation: as each page finishes OCR,
    its strips are immediately queued for nano validation (50 workers).
    Pages that fail assessment are re-sliced and enter the next round.

    Returns:
        List of per-page iteration reports.
    """
    _load_env()

    from openai import AsyncOpenAI

    cfg = load_config(book_id)
    logger.info("Loaded config for book: %s", cfg.book_id or "(default)")

    # Preflight: validate env, data, init OCR engine (reused below)
    _page_count, ocr_engine = _preflight_check(strips_dir)

    # Reconfigure OCR engine lang if needed
    if cfg.bronze_mirror.ocr_lang != "ch":
        from bronze_mirror.ocr.paddle_engine import OcrEngine
        ocr_engine = OcrEngine(lang=cfg.bronze_mirror.ocr_lang)

    nano_client = AsyncOpenAI()
    nano_semaphore = asyncio.Semaphore(cfg.platinum_scale.max_workers)

    ih = cfg.ivory_helm
    strategies = ih.reslice_strategies

    # Collect all page directories
    vol_dirs = sorted(d for d in strips_dir.iterdir() if d.is_dir() and d.name.startswith("vol"))
    if not vol_dirs:
        vol_dirs = [strips_dir]

    all_reports: list[dict] = []
    pending: list[dict] = []
    resumed = 0

    for vol_dir in vol_dirs:
        page_dirs = sorted(
            d for d in vol_dir.iterdir()
            if d.is_dir() and d.name.startswith("page_")
        )

        for page_dir in page_dirs:
            if resume:
                report_path = page_dir / "iteration_report.json"
                if report_path.exists():
                    with open(report_path, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                    if existing.get("final_status") == "pass":
                        all_reports.append(existing)
                        resumed += 1
                        continue

            page_image_path = page_dir / "page_image.png"
            if not page_image_path.exists():
                page_image_path = None
                if source_images_dir:
                    candidates = list(source_images_dir.glob(f"{page_dir.name}.*"))
                    if candidates:
                        page_image_path = candidates[0]

            try:
                page_num = int(page_dir.name.split("_")[1])
            except (IndexError, ValueError):
                page_num = 0

            pdf_name = "unknown"
            det_path = page_dir / "detection.json"
            if det_path.exists():
                with open(det_path, "r", encoding="utf-8") as f:
                    det = json.load(f)
                pdf_name = det.get("source_pdf", "unknown")

            pending.append({
                "page_dir": page_dir,
                "page_image_path": page_image_path,
                "page_num": page_num,
                "pdf_name": pdf_name,
                "book_id": cfg.book_id,
                "iterations": [],
                "final_status": "unknown",
            })

    if resumed:
        logger.info("Resumed: %d pages already passed", resumed)
    logger.info("Queue: %d pages to process", len(pending))

    total_pages = len(all_reports) + len(pending)
    _write_progress(strips_dir, book_id, "starting",
                    total_pages=total_pages, pending=len(pending), resumed=resumed)

    total_passed = len(all_reports)  # includes resumed
    total_best_effort = 0

    # --- Iteration rounds ---
    round_num = 0
    try:
        for round_num in range(ih.max_iterations):
            if not pending:
                break

            # Re-slice failed pages (round > 0)
            if round_num > 0:
                strategy_idx = round_num - 1
                if strategy_idx >= len(strategies):
                    logger.info("No more re-slice strategies — accepting best effort")
                    break

                strategy = strategies[strategy_idx]
                logger.info("Re-slicing %d pages (k=%d, t=%.2f)",
                           len(pending), strategy["smooth_k"], strategy["threshold_pct"])
                for job in pending:
                    if job["page_image_path"]:
                        _reslice_page(
                            job["page_image_path"], job["page_dir"], strategy,
                            job["page_num"], job["pdf_name"], cfg,
                        )

            # Run pipelined round
            passed, failed = await _run_pipeline_round(
                pending, round_num, ocr_engine, nano_client, nano_semaphore, cfg,
            )

            for job in passed:
                all_reports.append({
                    "page_label": job["page_dir"].name,
                    "page_num": job["page_num"],
                    "book_id": job["book_id"],
                    "iterations": job["iterations"],
                    "final_status": "pass",
                })

            total_passed += len(passed)
            pending = failed

            _write_progress(strips_dir, book_id, "running",
                            round_num=round_num + 1, total_pages=total_pages,
                            passed=total_passed, pending=len(pending),
                            best_effort=total_best_effort, resumed=resumed)

        # Mark remaining as best_effort
        for job in pending:
            job["final_status"] = "best_effort"
            _write_report(job)
            all_reports.append({
                "page_label": job["page_dir"].name,
                "page_num": job["page_num"],
                "book_id": job["book_id"],
                "iterations": job["iterations"],
                "final_status": "best_effort",
            })
            total_best_effort += 1

        final_round = round_num + 1 if total_passed > resumed or total_best_effort else 0
        _write_progress(strips_dir, book_id, "complete",
                        round_num=final_round, total_pages=total_pages,
                        passed=total_passed, pending=0,
                        best_effort=total_best_effort, resumed=resumed)

    except Exception:
        _write_progress(strips_dir, book_id, "error",
                        total_pages=total_pages, passed=total_passed,
                        pending=len(pending), best_effort=total_best_effort,
                        resumed=resumed, error=traceback.format_exc())
        raise

    return all_reports
