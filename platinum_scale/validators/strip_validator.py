"""Validate strip OCR results using gpt-4.1-nano (text-based, no vision).

Reads Bronze Mirror's per-strip OCR output (ocr_strip_NNN.json), sends
the OCR text + metadata to nano for classification.

Pipeline position:
  silver_gauge (slice) → bronze_mirror phase1 (OCR strips) → platinum_scale (validate) → bronze_mirror phase2 (merge)

Classifications:
- text: Body text, include in merge
- header: Running header/footer/page number — exclude from merge
- blank: Strip OCR returned no/trivial text — exclude
- noise: OCR artifacts, not real content — exclude
- merged: Text from multiple columns was merged — flag for review

Cost: ~$0.002 per chapter (text-only, no vision tokens).
"""

import asyncio
import json
import logging
from pathlib import Path

from openai import AsyncOpenAI

from platinum_scale.config.defaults import (
    MAX_WORKERS,
    MIN_CHARS_FOR_BODY_TEXT,
    OCR_HIGH_CONFIDENCE_THRESHOLD,
    VALIDATION_MAX_TOKENS,
    VALIDATION_MODEL,
    VALIDATION_TEMPERATURE,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You validate OCR output from individual column strips of a scanned classical Chinese book (vertical text, 1920s typography, read right-to-left).

Each strip was detected as a single vertical text column by the column detection stage, then OCR'd by PaddleOCR. You see the OCR text, character count, confidence, and strip width.

Classify each strip's OCR output into exactly ONE category:
- text: Real body text content. Include in the final merged output.
- header: Running header, footer, page number, chapter marker (e.g. 三俠五義, 第N回, bare numerals). Exclude from merge.
- blank: Empty or near-empty OCR result (0-2 chars). Exclude.
- noise: OCR artifacts, stray punctuation, garbled non-content. Exclude.
- merged: Text that appears to contain content from multiple columns (unusually long, topic shifts mid-strip). Flag for review.

Respond in JSON only:
{"classification": "text", "confidence": 0.92, "reason": "40 chars of coherent classical Chinese narrative"}

The confidence field (0.0–1.0) reflects your certainty in the classification."""


async def _validate_strip(
    client: AsyncOpenAI,
    strip_ocr: dict,
    page_context: str,
    semaphore: asyncio.Semaphore,
) -> dict:
    """Validate a single strip's OCR output via nano.

    Args:
        client: AsyncOpenAI client.
        strip_ocr: Dict from ocr_strip_NNN.json.
        page_context: Brief page context string.
        semaphore: Concurrency limiter.

    Returns:
        Validation result dict.
    """
    strip_index = strip_ocr.get("strip_index", "?")
    strip_file = strip_ocr.get("strip_file", "?")
    text = strip_ocr.get("text", "")
    status = strip_ocr.get("status", "unknown")
    chars = strip_ocr.get("chars", 0)
    box_count = strip_ocr.get("box_count", 0)
    ocr_confidence = strip_ocr.get("confidence_mean")

    # Fast path: already skipped or missing — no API call needed
    if status in ("skipped", "missing"):
        return {
            "strip_index": strip_index,
            "strip_file": strip_file,
            "nano_classification": "blank" if status == "missing" else strip_ocr.get("skip_reason", "header"),
            "reason": f"Already {status} by Silver Gauge",
            "ocr_confidence": ocr_confidence,
            "ps_confidence": None,
            "high_confidence_bypass": False,
            "agreement": True,
            "status": "pass_through",
            "input_tokens": 0,
            "output_tokens": 0,
        }

    # Fast path: truly empty OCR
    if status == "empty" or chars == 0:
        return {
            "strip_index": strip_index,
            "strip_file": strip_file,
            "nano_classification": "blank",
            "reason": "OCR returned 0 boxes/chars",
            "ocr_confidence": ocr_confidence,
            "ps_confidence": None,
            "high_confidence_bypass": False,
            "agreement": True,
            "status": "fast_blank",
            "input_tokens": 0,
            "output_tokens": 0,
        }

    # Fast path: high OCR confidence — skip nano, auto-classify as text
    if ocr_confidence is not None and ocr_confidence >= OCR_HIGH_CONFIDENCE_THRESHOLD:
        return {
            "strip_index": strip_index,
            "strip_file": strip_file,
            "nano_classification": "text",
            "reason": f"OCR confidence {ocr_confidence:.4f} >= {OCR_HIGH_CONFIDENCE_THRESHOLD} threshold",
            "ocr_text_preview": text[:80],
            "ocr_chars": chars,
            "ocr_confidence": ocr_confidence,
            "ps_confidence": None,
            "high_confidence_bypass": True,
            "agreement": True,
            "status": "high_confidence",
            "input_tokens": 0,
            "output_tokens": 0,
        }

    # Fast path: enough chars to be body text — real headers are short (≤15 chars)
    if chars >= MIN_CHARS_FOR_BODY_TEXT:
        return {
            "strip_index": strip_index,
            "strip_file": strip_file,
            "nano_classification": "text",
            "reason": f"{chars} chars >= {MIN_CHARS_FOR_BODY_TEXT} min body threshold",
            "ocr_text_preview": text[:80],
            "ocr_chars": chars,
            "ocr_confidence": ocr_confidence,
            "ps_confidence": None,
            "high_confidence_bypass": False,
            "agreement": True,
            "status": "char_count_text",
            "input_tokens": 0,
            "output_tokens": 0,
        }

    async with semaphore:
        try:
            user_msg = (
                f"{page_context}\n"
                f"Strip {strip_index} ({strip_file}):\n"
                f"  OCR text ({chars} chars, {box_count} boxes, "
                f"confidence={ocr_confidence}): \"{text}\"\n"
                f"Classify this strip."
            )

            response = await client.chat.completions.create(
                model=VALIDATION_MODEL,
                max_tokens=VALIDATION_MAX_TOKENS,
                temperature=VALIDATION_TEMPERATURE,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            result = json.loads(content)
            ps_conf = result.get("confidence")
            if ps_conf is not None:
                ps_conf = round(float(ps_conf), 4)

            return {
                "strip_index": strip_index,
                "strip_file": strip_file,
                "nano_classification": result.get("classification", "unknown"),
                "reason": result.get("reason", ""),
                "ocr_text_preview": text[:80],
                "ocr_chars": chars,
                "ocr_confidence": ocr_confidence,
                "ps_confidence": ps_conf,
                "high_confidence_bypass": False,
                "agreement": result.get("classification") == "text",
                "status": "validated",
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            }

        except Exception as e:
            logger.warning("Failed to validate strip %s: %s", strip_file, e)
            return {
                "strip_index": strip_index,
                "strip_file": strip_file,
                "nano_classification": "text",  # Default to include on error
                "reason": f"Validation error: {e}",
                "ocr_chars": chars,
                "ocr_confidence": ocr_confidence,
                "ps_confidence": None,
                "high_confidence_bypass": False,
                "agreement": True,
                "status": "error",
                "input_tokens": 0,
                "output_tokens": 0,
            }


async def validate_page(
    page_dir: Path,
    client: AsyncOpenAI,
    semaphore: asyncio.Semaphore,
) -> dict:
    """Validate all OCR strip results in a page directory.

    Reads detection.json + ocr_strip_NNN.json files, validates via nano,
    writes validation.json.

    Returns page validation summary.
    """
    detection_path = page_dir / "detection.json"
    if not detection_path.exists():
        return {"page_label": page_dir.name, "status": "no_detection", "strips": []}

    with open(detection_path, "r", encoding="utf-8") as f:
        detection = json.load(f)

    strips_meta = detection.get("strips", [])
    if not strips_meta:
        return {"page_label": page_dir.name, "status": "no_strips", "strips": []}

    # Check that OCR has been run (Phase 1 must complete first)
    ocr_files = list(page_dir.glob("ocr_strip_*.json"))
    if not ocr_files:
        return {"page_label": page_dir.name, "status": "no_ocr_results", "strips": []}

    # Build page context string
    page_context = (
        f"Page: {detection.get('page_label', page_dir.name)}, "
        f"source: {detection.get('source_pdf', '?')}, "
        f"page {detection.get('page_num_in_pdf', '?')}, "
        f"{len(strips_meta)} strips detected."
    )

    # Load all OCR results
    strip_ocr_results = {}
    for strip_info in strips_meta:
        idx = strip_info["index"]
        ocr_path = page_dir / f"ocr_strip_{idx:03d}.json"
        if ocr_path.exists():
            with open(ocr_path, "r", encoding="utf-8") as f:
                strip_ocr_results[idx] = json.load(f)

    # Validate all strips in parallel
    tasks = []
    for strip_info in strips_meta:
        idx = strip_info["index"]
        if idx in strip_ocr_results:
            tasks.append(_validate_strip(
                client, strip_ocr_results[idx], page_context, semaphore,
            ))

    results = await asyncio.gather(*tasks) if tasks else []

    # Build summary
    total_input = sum(r.get("input_tokens", 0) for r in results)
    total_output = sum(r.get("output_tokens", 0) for r in results)
    kept = sum(1 for r in results if r.get("nano_classification") == "text")
    excluded = sum(1 for r in results if r.get("nano_classification") in ("header", "blank", "noise"))
    high_conf_bypassed = sum(1 for r in results if r.get("high_confidence_bypass"))
    nano_called = sum(1 for r in results if r.get("status") == "validated")

    summary = {
        "page_label": detection.get("page_label", page_dir.name),
        "source_pdf": detection.get("source_pdf", ""),
        "page_num_in_pdf": detection.get("page_num_in_pdf"),
        "total_strips": len(strips_meta),
        "validated": len(results),
        "kept": kept,
        "excluded": excluded,
        "high_confidence_bypassed": high_conf_bypassed,
        "nano_api_calls": nano_called,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "strips": results,
        "status": "validated",
    }

    # Write validation.json
    validation_path = page_dir / "validation.json"
    with open(validation_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return summary


async def validate_book(
    strips_dir: Path,
    resume: bool = True,
    max_workers: int = MAX_WORKERS,
) -> list[dict]:
    """Validate all pages in a book's strip directory.

    Requires Bronze Mirror Phase 1 (per-strip OCR) to have completed.

    Args:
        strips_dir: Root directory containing vol*/ subdirectories.
        resume: Skip pages where validation.json already exists.
        max_workers: Max concurrent API calls.

    Returns:
        List of page validation summaries.
    """
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / "iron_abacus_translator" / ".env")

    client = AsyncOpenAI()
    semaphore = asyncio.Semaphore(max_workers)

    # Find all volume directories
    vol_dirs = sorted(d for d in strips_dir.iterdir() if d.is_dir() and d.name.startswith("vol"))
    if not vol_dirs:
        vol_dirs = [strips_dir]

    page_tasks = []
    skipped = 0

    for vol_dir in vol_dirs:
        page_dirs = sorted(
            d for d in vol_dir.iterdir()
            if d.is_dir() and d.name.startswith("page_")
        )

        for page_dir in page_dirs:
            # Resume: skip if already validated
            if resume and (page_dir / "validation.json").exists():
                skipped += 1
                continue
            page_tasks.append(validate_page(page_dir, client, semaphore))

    if skipped:
        logger.info("Skipped %d already-validated pages", skipped)

    results = await asyncio.gather(*page_tasks) if page_tasks else []
    return list(results)
