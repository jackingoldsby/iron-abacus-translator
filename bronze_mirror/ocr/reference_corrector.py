"""LLM-powered OCR correction using a clean reference text (e.g. EPUB edition).

Operates on the raw JSON emitted by json_emitter. For each chapter:
  1. Concatenates all OCR content blocks into a single text stream
  2. Sends it to the LLM alongside the reference chapter text
  3. Gets back corrected text with proper paragraph breaks
  4. Splits the corrected output into new content blocks

OCR blocks (page-boundary artefacts) don't align with EPUB paragraphs, so
we correct at the chapter level and re-block the output.  Provenance is
tracked per-chapter (source PDFs + page range from the original blocks).

The reference is a *different edition* (e.g. standard 石玉昆 text vs
俞平伯校點本), so the corrector preserves editorial differences and
scholarly apparatus unique to the scanned edition.

Uses DeepSeek (cheap, excellent Chinese) by default.
"""

import asyncio
import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reference loader
# ---------------------------------------------------------------------------


def load_reference_chapters(ref_path: Path) -> dict[int, dict]:
    """Load cleaned EPUB JSON and index chapters by ordinal (回 number).

    Returns:
        {1: {"title": "第一回 ...", "text": "full chapter text"}, ...}
    """
    with open(ref_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    body = data.get("structure", data).get("body", data)
    chapters = body.get("chapters", [])

    indexed = {}
    for ch in chapters:
        ordinal = ch.get("ordinal")
        title = ch.get("title", "")

        if not ordinal:
            m = re.search(r"第([一二三四五六七八九十百零廿卅\d]+)回", title)
            if m:
                ordinal = _chinese_num(m.group(1))
            else:
                continue

        blocks = ch.get("content_blocks", [])
        text = "\n\n".join(
            b.get("content", "") for b in blocks
            if b.get("type") in ("paragraph", "verse", "p", None)
        )
        if not text:
            content = ch.get("content", [])
            if isinstance(content, list):
                text = "\n\n".join(
                    b.get("content", "") if isinstance(b, dict) else str(b)
                    for b in content
                )

        indexed[ordinal] = {"title": title, "text": text}

    logger.info("Loaded %d reference chapters from %s", len(indexed), ref_path.name)
    return indexed


def _chinese_num(s: str) -> int:
    """Convert Chinese numeral string to int. Handles 一 through 百二十."""
    if s.isdigit():
        return int(s)
    mapping = {
        "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        "百": 100, "廿": 20, "卅": 30,
    }
    result = 0
    current = 0
    for ch in s:
        val = mapping.get(ch, -1)
        if val < 0:
            continue
        if val == 100:
            result += (current or 1) * 100
            current = 0
        elif val == 10:
            result += (current or 1) * 10
            current = 0
        else:
            current = val
    return result + current


# ---------------------------------------------------------------------------
# Chunking — split long chapters to fit API context
# ---------------------------------------------------------------------------

_MAX_CHARS_PER_CALL = 3000


def _chunk_chapter(ocr_text: str, ref_text: str,
                    max_chars: int = _MAX_CHARS_PER_CALL
                    ) -> list[tuple[str, str]]:
    """Split a chapter into (ocr_chunk, ref_chunk) pairs for API calls.

    Short chapters go as a single call.  Long ones are split on paragraph
    boundaries (double newlines), with the reference window aligned to each
    OCR chunk using character overlap.
    """
    if len(ocr_text) <= max_chars:
        return [(ocr_text, ref_text)]

    # Split OCR on line breaks, accumulate into chunks
    lines = ocr_text.split("\n")
    ocr_chunks = []
    current = []
    current_len = 0
    for line in lines:
        if current_len + len(line) > max_chars and current:
            ocr_chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line)
    if current:
        ocr_chunks.append("\n".join(current))

    # Align each OCR chunk to a reference window
    pairs = []
    cursor = 0
    for chunk in ocr_chunks:
        ref_window, cursor = _align_window(chunk, ref_text, cursor)
        pairs.append((chunk, ref_window))

    return pairs


def _align_window(ocr_text: str, ref_text: str, cursor: int) -> tuple[str, int]:
    """Find the reference window best matching an OCR chunk."""
    window_size = max(len(ocr_text) * 2, 600)

    if len(ref_text) <= window_size:
        return ref_text, cursor

    cjk = re.findall(r"[\u4e00-\u9fff]", ocr_text[:80])
    anchor = "".join(cjk[:10])

    if not anchor:
        start = max(0, cursor - 100)
        end = min(len(ref_text), start + window_size)
        return ref_text[start:end], cursor

    best_pos = cursor
    best_score = 0

    # Search near cursor first
    search_start = max(0, cursor - 300)
    search_end = min(len(ref_text) - len(anchor), cursor + window_size * 2)
    for i in range(search_start, search_end, 10):
        score = sum(1 for a, b in zip(anchor, ref_text[i:i + len(anchor)]) if a == b)
        if score > best_score:
            best_score = score
            best_pos = i

    # Broaden if poor match
    if best_score < len(anchor) * 0.4:
        for i in range(0, len(ref_text) - len(anchor), 20):
            score = sum(1 for a, b in zip(anchor, ref_text[i:i + len(anchor)]) if a == b)
            if score > best_score:
                best_score = score
                best_pos = i

    start = max(0, best_pos - 100)
    end = min(len(ref_text), start + window_size)
    return ref_text[start:end], best_pos + len(ocr_text)


# ---------------------------------------------------------------------------
# LLM correction
# ---------------------------------------------------------------------------

_BODY_SYSTEM_PROMPT = """\
You are an expert in Classical Chinese text correction and structuring.

You receive raw OCR output from a scanned 1920s critical edition of a novel. \
The OCR text is a wall of page-concatenated lines with character errors from \
scanning. You also receive a section of a clean digital reference text (a \
different, standard edition of the same work) to help identify OCR errors.

You have TWO jobs:

## Job 1: Fix OCR errors
Cross-reference the clean text to fix character-level scan errors \
(e.g. 最陰課→設陰謀, 粉粉→紛紛, 的的→的一, 甜死→勒死, 腿→祖, 叉→又). \
PRESERVE text unique to the scanned edition (editorial notes, punctuation \
differences, variant readings) — do NOT delete it.

## Job 2: Restructure into semantic blocks
The OCR gives you raw lines with meaningless page-boundary breaks. The \
reference has big monolithic paragraphs. Neither has good structure.

Restructure the text into semantic content blocks. Each block should be ONE of:
- "verse" — a poem/verse passage (詩曰, 詞曰, etc.)
- "dialogue" — one speaker's turn of dialogue
- "narrative" — one scene, action sequence, or description
- "descriptive" — a scene-setting passage or physical description
- "thought" — a character's internal monologue (暗想, 心中想道, etc.)

Break on: scene changes, speaker turns, verse↔prose transitions, topic shifts, \
time jumps (e.g. 且說, 話說, 再說, 卻說). Aim for blocks of 50-300 characters.

## Output format
Output a JSON array of objects. Each object has:
- "type": one of "verse", "dialogue", "narrative", "descriptive", "thought"
- "content": the corrected Chinese text for that block

REMOVE running headers/page artifacts (stray "三俠五義", "第一回", page numbers).
Output ONLY the JSON array — no markdown fences, no preamble."""


_APPARATUS_SYSTEM_PROMPT = """\
You are an expert in Classical Chinese philology and textual criticism.

You receive raw OCR output from the scholarly apparatus of a 1920s critical \
edition (俞平伯校點本). This includes prefaces (序), postscripts (跋), \
collation notes (校勘記), editorial commentary, and textual variants. The OCR \
has character-level errors from scanning.

You may also receive a section of the novel text from a standard digital \
edition — this is NOT the apparatus itself but may help you identify \
character errors where the apparatus quotes from the novel.

You have TWO jobs:

## Job 1: Fix OCR errors
Fix character-level scan errors. Be especially careful with:
- Scholar names, dynasty names, book titles
- Bibliographic references and textual variant citations
- Classical Chinese grammatical particles (之、乎、者、也)
- Quotation marks and punctuation conventions

## Job 2: Restructure into semantic blocks
Restructure into blocks. Each block should be ONE of:
- "preface" — preface (序), postscript (跋), editorial introduction
- "commentary" — collation notes (校勘記), editorial commentary, textual criticism, \
  variant readings
- "verse" — quoted poetry
- "descriptive" — bibliographic description or physical book description

Break on: topic shifts, citation boundaries, new collation entries, \
section headings. Aim for blocks of 50-400 characters.

## Output format
Output a JSON array of objects. Each object has:
- "type": one of "preface", "commentary", "verse", "descriptive"
- "content": the corrected Chinese text for that block

REMOVE page artifacts. Output ONLY the JSON array — no markdown fences, \
no preamble."""


_USER_TEMPLATE = """\
## OCR text (to correct and restructure)
{ocr_text}

## Reference (clean edition — may differ editorially)
{ref_text}"""


async def _correct_chunk(
    ocr_text: str,
    ref_text: str,
    client,
    semaphore: asyncio.Semaphore,
    model: str,
    system_prompt: str = "",
) -> list[dict]:
    """Correct one chunk of OCR text, returning structured JSON blocks.

    Returns list of {"type": ..., "content": "corrected text"}.
    On failure, falls back to a single narrative block with original text.
    """
    if not ocr_text.strip():
        return []

    prompt = system_prompt or _BODY_SYSTEM_PROMPT

    async with semaphore:
        resp = None
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": _USER_TEMPLATE.format(
                        ocr_text=ocr_text, ref_text=ref_text,
                    )},
                ],
                temperature=0.1,
                max_tokens=min(len(ocr_text) * 3 + 1000, 8192),
            )
            raw = resp.choices[0].message.content.strip()

            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
                raw = re.sub(r"\n?```\s*$", "", raw)

            blocks = json.loads(raw)
            if not isinstance(blocks, list):
                raise ValueError("Expected JSON array")

            valid = []
            for b in blocks:
                if isinstance(b, dict) and "content" in b and b["content"].strip():
                    valid.append({
                        "type": b.get("type", "narrative"),
                        "content": b["content"].strip(),
                    })
            if not valid:
                raise ValueError("No valid blocks in output")
            return valid

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("LLM returned non-JSON (%s) — wrapping as narrative", e)
            text = resp.choices[0].message.content.strip() if resp else ocr_text
            return [{"type": "narrative", "content": p.strip()}
                    for p in re.split(r"\n\s*\n", text) if p.strip()]

        except Exception as e:
            logger.error("LLM correction failed (%d chars): %s", len(ocr_text), e)
            return [{"type": "narrative", "content": ocr_text}]


async def _correct_title(
    ocr_title: str,
    ref_title: str,
    client,
    semaphore: asyncio.Semaphore,
    model: str,
) -> str:
    """Correct a chapter title (returns plain string, not blocks)."""
    if not ocr_title.strip():
        return ocr_title

    async with semaphore:
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": (
                        "Fix OCR errors in this Classical Chinese chapter title "
                        "using the reference. Output ONLY the corrected title."
                    )},
                    {"role": "user", "content": (
                        f"OCR: {ocr_title}\nReference: {ref_title}"
                    )},
                ],
                temperature=0.0,
                max_tokens=200,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error("Title correction failed: %s", e)
            return ocr_title


# ---------------------------------------------------------------------------
# Chapter-level correction: concat blocks → correct → JSON blocks out
# ---------------------------------------------------------------------------


def _extract_provenance(content_blocks: list[dict]) -> dict:
    """Extract chapter-level provenance from original content blocks."""
    source_pdfs = []
    page_nums = []
    for b in content_blocks:
        if not isinstance(b, dict):
            continue
        sp = b.get("source_pdf")
        if sp and sp not in source_pdfs:
            source_pdfs.append(sp)
        pages = b.get("source_pages", "")
        if pages:
            for part in str(pages).split("-"):
                try:
                    page_nums.append(int(part))
                except ValueError:
                    pass

    return {
        "source_pdf": source_pdfs[0] if source_pdfs else "",
        "source_pages": (f"{min(page_nums)}-{max(page_nums)}"
                         if page_nums else ""),
    }


async def _correct_chapter(
    ch: dict,
    ref: dict,
    client,
    semaphore: asyncio.Semaphore,
    model: str,
    is_apparatus: bool = False,
) -> dict:
    """Correct a single chapter's OCR and restructure into typed blocks.

    Args:
        is_apparatus: If True, use the scholarly apparatus prompt instead of
                      the novel body prompt.

    Returns a new chapter dict with content blocks that have "type" and "tag".
    """
    content_blocks = ch.get("content", [])
    provenance = _extract_provenance(content_blocks)

    # Concatenate all OCR blocks into one text stream
    ocr_text = "\n".join(
        b.get("content", "") for b in content_blocks if isinstance(b, dict)
    )

    if not ocr_text.strip():
        return ch

    ref_text = ref["text"]

    # Chunk if needed, correct each chunk (returns list[list[dict]])
    prompt = _APPARATUS_SYSTEM_PROMPT if is_apparatus else _BODY_SYSTEM_PROMPT
    chunks = _chunk_chapter(ocr_text, ref_text)
    tasks = [
        _correct_chunk(ocr_chunk, ref_chunk, client, semaphore, model, prompt)
        for ocr_chunk, ref_chunk in chunks
    ]
    chunk_results = await asyncio.gather(*tasks)

    # Flatten all blocks from all chunks
    all_blocks = []
    for block_list in chunk_results:
        all_blocks.extend(block_list)

    # Correct the title separately (plain text, not JSON)
    corrected_title = ch["title"]
    if ref.get("title"):
        corrected_title = await _correct_title(
            ch["title"], ref["title"], client, semaphore, model,
        )

    # Build output blocks with provenance and tag
    _TYPE_TO_TAG = {
        "verse": "verse",
        "dialogue": "p",
        "narrative": "p",
        "descriptive": "p",
        "thought": "p",
        "commentary": "p",
        "preface": "p",
    }

    new_blocks = []
    for b in all_blocks:
        block = {
            "tag": _TYPE_TO_TAG.get(b["type"], "p"),
            "type": b["type"],
            "content": b["content"],
        }
        if provenance["source_pdf"]:
            block["source_pdf"] = provenance["source_pdf"]
        if provenance["source_pages"]:
            block["source_pages"] = provenance["source_pages"]
        new_blocks.append(block)

    corrected_chars = sum(len(b["content"]) for b in new_blocks)

    return {
        "title": corrected_title,
        "content": new_blocks,
        "correction": {
            "ocr_chars": len(ocr_text),
            "corrected_chars": corrected_chars,
            "ocr_blocks": len(content_blocks),
            "corrected_blocks": len(new_blocks),
        },
    }


# ---------------------------------------------------------------------------
# Top-level: correct a full raw JSON
# ---------------------------------------------------------------------------


async def correct_raw_json(
    raw_json_path: Path,
    ref_path: Path,
    output_path: Path | None = None,
    model: str = "deepseek-chat",
    max_workers: int = 20,
) -> Path:
    """Correct OCR errors in raw JSON using a clean EPUB reference.

    For each chapter: concatenates OCR blocks → corrects against reference →
    re-splits into proper paragraph blocks.  Non-chapter sections (front
    matter, commentary without 回 number) pass through unchanged.

    Args:
        raw_json_path: Bronze Mirror raw JSON (from json_emitter).
        ref_path: Jade Shuttle cleaned JSON of the same work.
        output_path: Where to write corrected JSON. Defaults to *_corrected.json.
        model: LLM model for correction.
        max_workers: Concurrent API calls.

    Returns:
        Path to the corrected JSON file.
    """
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    load_dotenv(Path.home() / ".env")

    from openai import AsyncOpenAI

    with open(raw_json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    ref_chapters = load_reference_chapters(ref_path)

    if "deepseek" in model:
        client = AsyncOpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
        )
    else:
        client = AsyncOpenAI()

    semaphore = asyncio.Semaphore(max_workers)

    chapters = raw.get("chapters", [])
    stats = {"total": 0, "body": 0, "apparatus": 0, "no_ref": 0}

    # Launch all chapter corrections concurrently
    tasks = []
    for ch in chapters:
        stats["total"] += 1
        title = ch.get("title", "")

        m = re.search(r"第([一二三四五六七八九十百零廿卅\d]+)回", title)
        if m:
            # Novel body — match to reference chapter
            hui_num = _chinese_num(m.group(1))
            ref = ref_chapters.get(hui_num)
            if not ref:
                tasks.append(None)
                stats["no_ref"] += 1
                continue

            tasks.append(asyncio.create_task(
                _correct_chapter(ch, ref, client, semaphore, model,
                                 is_apparatus=False)
            ))
            stats["body"] += 1
        else:
            # Scholarly apparatus (preface, postscript, collation notes)
            # Use first reference chapter as loose context (or empty)
            ref_context = {"title": "", "text": ""}
            if ref_chapters:
                first_key = min(ref_chapters.keys())
                ref_context = ref_chapters[first_key]

            tasks.append(asyncio.create_task(
                _correct_chapter(ch, ref_context, client, semaphore, model,
                                 is_apparatus=True)
            ))
            stats["apparatus"] += 1

    # Await and assemble
    corrected_chapters = []
    for ch, task in zip(chapters, tasks):
        if task is None:
            corrected_chapters.append(ch)
        else:
            corrected_chapters.append(await task)

    # Build output
    raw["chapters"] = corrected_chapters
    raw["metadata"]["correction"] = {
        "reference": str(ref_path.name),
        "model": model,
        "stats": stats,
    }
    raw["number_of_characters"] = sum(
        len(b.get("content", ""))
        for ch in corrected_chapters
        for b in ch.get("content", [])
        if isinstance(b, dict)
    )

    if output_path is None:
        output_path = raw_json_path.with_name(
            raw_json_path.stem + "_corrected.json"
        )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)

    logger.info("Correction: %d chapters, %d corrected, %d pass-through, %d no-ref",
                stats["total"], stats["corrected"], stats["pass_through"], stats["no_ref"])
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    """CLI entry point for standalone correction."""
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Correct OCR using EPUB reference")
    parser.add_argument("raw_json", help="Bronze Mirror raw JSON file")
    parser.add_argument("ref_json", help="Jade Shuttle cleaned JSON (reference)")
    parser.add_argument("-o", "--output", help="Output path (default: *_corrected.json)")
    parser.add_argument("--model", default="deepseek-chat", help="LLM model")
    parser.add_argument("--workers", type=int, default=20, help="Concurrent API calls")
    args = parser.parse_args()

    result = asyncio.run(correct_raw_json(
        Path(args.raw_json),
        Path(args.ref_json),
        Path(args.output) if args.output else None,
        model=args.model,
        max_workers=args.workers,
    ))
    print(f"Corrected: {result}")


if __name__ == "__main__":
    main()
