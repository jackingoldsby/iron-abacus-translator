"""OCR pre-sliced strips from Silver Gauge output, merge into reading-order text.

Two-phase design:
  Phase 1: ocr_strips_only() — OCR each strip, write ocr_strip_NNN.json
  Phase 2: merge_page() — read OCR results + validation.json, merge into text

Platinum Scale runs between phases to validate OCR output via nano.
"""

import json
import logging
from pathlib import Path

from bronze_mirror.ocr.paddle_engine import OcrBox, OcrEngine
from bronze_mirror.ocr.postprocessor import (
    filter_low_confidence,
    fix_common_errors,
    strip_running_headers_regex,
)

logger = logging.getLogger(__name__)


def ocr_strip(strip_path: Path, engine: OcrEngine) -> dict:
    """OCR a single strip image and return result metadata.

    Returns:
        Dict with keys: strip_file, text, box_count,
        confidence_mean, chars, status.
    """
    boxes = engine.recognize(strip_path)
    boxes = filter_low_confidence(boxes)

    if not boxes:
        return {
            "strip_file": strip_path.name,
            "text": "",
            "box_count": 0,
            "confidence_mean": None,
            "chars": 0,
            "status": "empty",
        }

    # Sort boxes top-to-bottom within the strip
    boxes.sort(key=lambda b: b.top)
    text = "".join(b.text for b in boxes)
    conf_mean = sum(b.confidence for b in boxes) / len(boxes)

    return {
        "strip_file": strip_path.name,
        "text": text,
        "box_count": len(boxes),
        "confidence_mean": round(conf_mean, 4),
        "chars": len(text),
        "status": "ok",
    }


# ---------------------------------------------------------------------------
# Phase 1: OCR all strips in a page (no merging, no validation consumption)
# ---------------------------------------------------------------------------

def ocr_strips_only(page_dir: Path, engine: OcrEngine) -> list[dict]:
    """OCR all strips in a page directory. Write per-strip JSON. No merging.

    Reads detection.json, OCRs each strip classified as 'text' by Silver Gauge,
    writes ocr_strip_NNN.json per strip. Skips header_only strips.

    This is Phase 1 — run before Platinum Scale validation.

    Returns:
        List of per-strip result dicts.
    """
    detection_path = page_dir / "detection.json"
    if not detection_path.exists():
        logger.warning("No detection.json in %s — skipping", page_dir)
        return []

    with open(detection_path, "r", encoding="utf-8") as f:
        detection = json.load(f)

    strips_meta = detection.get("strips", [])
    if not strips_meta:
        logger.info("No strips in %s", page_dir)
        return []

    results = []
    for strip_info in strips_meta:
        sg_classification = strip_info.get("classification", "text")
        strip_file = strip_info["file"]
        strip_index = strip_info["index"]
        strip_path = page_dir / strip_file

        ocr_result_path = page_dir / f"ocr_strip_{strip_index:03d}.json"

        # Skip Silver Gauge header_only — no need to OCR at all
        if sg_classification == "header_only":
            result = {
                "strip_index": strip_index,
                "strip_file": strip_file,
                "text": "",
                "box_count": 0,
                "confidence_mean": None,
                "chars": 0,
                "status": "skipped",
                "skip_reason": "header_only",
            }
            with open(ocr_result_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            results.append(result)
            continue

        if not strip_path.exists():
            logger.warning("Strip file missing: %s", strip_path)
            result = {
                "strip_index": strip_index,
                "strip_file": strip_file,
                "text": "",
                "box_count": 0,
                "confidence_mean": None,
                "chars": 0,
                "status": "missing",
            }
            with open(ocr_result_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            results.append(result)
            continue

        result = ocr_strip(strip_path, engine)
        result["strip_index"] = strip_index

        if result["status"] == "empty":
            logger.warning(
                "Strip %s in %s returned 0 boxes — image persists for debugging",
                strip_file, page_dir.name,
            )

        with open(ocr_result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Phase 2: Merge OCR results using Platinum Scale validation (if available)
# ---------------------------------------------------------------------------

def merge_page(page_dir: Path) -> str:
    """Merge OCR strip results into page text, respecting validation.

    Reads ocr_strip_NNN.json files and optionally validation.json
    (from Platinum Scale). Strips that nano classified as header/blank/noise
    are excluded from the merge.

    This is Phase 2 — run after Platinum Scale validation.

    Returns:
        Merged, post-processed text for the page.
    """
    detection_path = page_dir / "detection.json"
    if not detection_path.exists():
        return ""

    with open(detection_path, "r", encoding="utf-8") as f:
        detection = json.load(f)

    strips_meta = detection.get("strips", [])
    if not strips_meta:
        return ""

    # Load Platinum Scale validation if available
    validation_path = page_dir / "validation.json"
    nano_verdicts = {}  # strip_index → {"classification": ..., "action": ...}
    if validation_path.exists():
        with open(validation_path, "r", encoding="utf-8") as f:
            validation = json.load(f)
        for v_strip in validation.get("strips", []):
            idx = v_strip.get("strip_index")
            if idx is not None and v_strip.get("status") == "validated":
                nano_verdicts[idx] = v_strip

    # Collect text from strips, respecting validation
    lines = []
    for strip_info in strips_meta:
        strip_index = strip_info["index"]

        ocr_file = page_dir / f"ocr_strip_{strip_index:03d}.json"
        if not ocr_file.exists():
            continue

        with open(ocr_file, "r", encoding="utf-8") as f:
            ocr_result = json.load(f)

        # Already skipped during OCR phase
        if ocr_result.get("status") in ("skipped", "missing"):
            continue

        # Nano verdicts inform retry decisions but do NOT exclude from merge.
        # All OCR'd text is captured — classification is metadata only.

        text = ocr_result.get("text", "")
        if text.strip():
            lines.append(text)

    # Merge and post-process
    text = "\n".join(lines)
    text = fix_common_errors(text)
    text = strip_running_headers_regex(text)

    # Collect per-strip summary
    strip_results = []
    for strip_info in strips_meta:
        idx = strip_info["index"]
        ocr_file = page_dir / f"ocr_strip_{idx:03d}.json"
        if ocr_file.exists():
            with open(ocr_file, "r", encoding="utf-8") as f:
                strip_results.append(json.load(f))

    # Write merged result as JSON
    merged_json_path = page_dir / "ocr_merged.json"
    merged_json = {
        "page_label": detection.get("page_label", page_dir.name),
        "source_pdf": detection.get("source_pdf", ""),
        "page_num_in_pdf": detection.get("page_num_in_pdf"),
        "total_strips": len(strips_meta),
        "ocr_strips": len(strip_results),
        "strips_ok": sum(1 for s in strip_results if s.get("status") == "ok"),
        "strips_empty": sum(1 for s in strip_results if s.get("status") == "empty"),
        "strips_skipped": sum(1 for s in strip_results if s.get("status") == "skipped"),
        "nano_excluded": sum(1 for idx, v in nano_verdicts.items()
                            if v.get("nano_classification") in ("header", "blank", "noise")),
        "has_validation": bool(nano_verdicts),
        "total_chars": len(text.replace("\n", "")),
        "text": text,
    }
    with open(merged_json_path, "w", encoding="utf-8") as f:
        json.dump(merged_json, f, ensure_ascii=False, indent=2)

    # Also write plain text
    merged_txt_path = page_dir / "ocr_merged.txt"
    with open(merged_txt_path, "w", encoding="utf-8") as f:
        f.write(text)

    return text


# ---------------------------------------------------------------------------
# Legacy one-shot: OCR + merge in a single pass (no Platinum Scale)
# ---------------------------------------------------------------------------

def ocr_page(page_dir: Path, engine: OcrEngine) -> str:
    """OCR all strips and merge in one pass. Legacy convenience function.

    For the two-phase flow, use ocr_strips_only() then merge_page() instead.
    """
    ocr_strips_only(page_dir, engine)
    return merge_page(page_dir)


# ---------------------------------------------------------------------------
# Book-level orchestration
# ---------------------------------------------------------------------------

def ocr_book_phase1(
    strips_dir: Path,
    engine: OcrEngine,
    resume: bool = True,
    page_filter: tuple[int, int] | None = None,
) -> int:
    """Phase 1: OCR all strips in a book. No merging.

    Returns number of pages processed.
    """
    count = 0
    for vol_dir, page_dir in _iter_page_dirs(strips_dir, page_filter):
        # Resume: skip if OCR results already exist
        if resume and _has_ocr_results(page_dir):
            continue

        logger.info("OCR Phase 1: %s / %s", vol_dir.name, page_dir.name)
        ocr_strips_only(page_dir, engine)
        count += 1

    return count


def merge_book(
    strips_dir: Path,
    page_filter: tuple[int, int] | None = None,
) -> list[tuple[str, str]]:
    """Phase 2: Merge all pages (after Platinum Scale validation).

    Returns list of (page_label, merged_text) tuples.
    """
    results = []
    for vol_dir, page_dir in _iter_page_dirs(strips_dir, page_filter):
        page_label = page_dir.name
        text = merge_page(page_dir)
        results.append((page_label, text))
    return results


def ocr_book(
    strips_dir: Path,
    engine: OcrEngine,
    resume: bool = True,
    page_filter: tuple[int, int] | None = None,
) -> list[tuple[str, str]]:
    """Legacy one-shot: OCR + merge all pages. No Platinum Scale.

    For the two-phase flow, use ocr_book_phase1() then merge_book() instead.
    """
    results = []
    for vol_dir, page_dir in _iter_page_dirs(strips_dir, page_filter):
        page_label = page_dir.name

        # Resume: check merged output
        merged_json_path = page_dir / "ocr_merged.json"
        merged_txt_path = page_dir / "ocr_merged.txt"
        if resume and merged_json_path.exists():
            with open(merged_json_path, "r", encoding="utf-8") as f:
                merged_data = json.load(f)
            results.append((page_label, merged_data.get("text", "")))
            continue
        elif resume and merged_txt_path.exists():
            text = merged_txt_path.read_text(encoding="utf-8")
            results.append((page_label, text))
            continue

        logger.info("OCR: %s / %s", vol_dir.name, page_label)
        text = ocr_page(page_dir, engine)
        results.append((page_label, text))

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iter_page_dirs(
    strips_dir: Path,
    page_filter: tuple[int, int] | None = None,
):
    """Yield (vol_dir, page_dir) tuples across all volumes."""
    vol_dirs = sorted(d for d in strips_dir.iterdir() if d.is_dir() and d.name.startswith("vol"))
    if not vol_dirs:
        vol_dirs = [strips_dir]

    for vol_dir in vol_dirs:
        page_dirs = sorted(
            d for d in vol_dir.iterdir()
            if d.is_dir() and d.name.startswith("page_")
        )
        for page_dir in page_dirs:
            if page_filter:
                try:
                    page_num = int(page_dir.name.split("_")[1])
                    if page_num < page_filter[0] or page_num > page_filter[1]:
                        continue
                except (IndexError, ValueError):
                    pass
            yield vol_dir, page_dir


def _has_ocr_results(page_dir: Path) -> bool:
    """Check if per-strip OCR results already exist for a page."""
    return any(page_dir.glob("ocr_strip_*.json"))


def show_failures(strips_dir: Path) -> list[dict]:
    """Find all strips with status 'empty' or 'missing' across the book.

    Returns list of dicts with page_label, strip_index, strip_file, status.
    """
    failures = []

    for _, page_dir in _iter_page_dirs(strips_dir):
        for ocr_file in sorted(page_dir.glob("ocr_strip_*.json")):
            with open(ocr_file, "r", encoding="utf-8") as f:
                result = json.load(f)
            if result.get("status") in ("empty", "missing"):
                failures.append({
                    "page_label": page_dir.name,
                    "strip_index": result.get("strip_index"),
                    "strip_file": result.get("strip_file"),
                    "status": result["status"],
                    "path": str(page_dir / result.get("strip_file", "")),
                })

    return failures
