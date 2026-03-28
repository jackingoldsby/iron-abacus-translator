#!/usr/bin/env python3
"""
DAG Pipeline Validation - Translate 6 chapters from 2 Liang Yusheng books.

Translates chapters 1-3 from:
  - D13G9 大唐游俠傳 (The Legend of the Knights of the Tang Dynasty)
  - I09B3 武林天驕 (Martial Arts Prodigy)

Produces translated JSON + EPUB for each book.
"""

import sys
import json
import logging
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "crimson_folio"))

# Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

import dotenv
dotenv.load_dotenv()

from processors.translator import TranslationService, TranslationRequest
from builders.epub_builder import EpubBuilder
from tqdm import tqdm
from dataclasses import asdict

# Constants
from utils.environment_config import get_or_create_config
BASE = get_or_create_config().source_dir
OUTPUT_DIR = Path("translation_data/dag_validation")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BOOKS = [
    {
        "work_id": "D13G9",
        "path": BASE / "wuxia_0120/cleaned_D13G9_大唐游俠傳_梁羽生.json",
        "chapters": 3,
    },
    {
        "work_id": "I09B3",
        "path": BASE / "wuxia_0123/cleaned_I09B3_武林天驕_梁羽生.json",
        "chapters": 3,
    },
]


def translate_book_chapters(book_info, service):
    """Translate N consecutive chapters from a book."""
    work_id = book_info["work_id"]
    n_chapters = book_info["chapters"]

    logger.info(f"\n{'='*60}")
    logger.info(f"Translating {work_id}: first {n_chapters} chapters")
    logger.info(f"{'='*60}")

    with open(book_info["path"], "r", encoding="utf-8") as f:
        book_data = json.load(f)

    meta = book_data.get("meta", book_data.get("metadata", {}))
    chapters = book_data.get("structure", {}).get("body", {}).get("chapters", [])
    logger.info(f"Book has {len(chapters)} total chapters")

    chapters_to_translate = chapters[:n_chapters]
    translated_chapters = []
    total_footnotes = 0
    total_blocks = 0
    start = time.time()

    for ch_idx, chapter in enumerate(chapters_to_translate):
        heading = chapter.get("heading", chapter.get("title", f"Chapter {ch_idx+1}"))
        blocks = chapter.get("content_blocks", [])
        logger.info(f"\nChapter {ch_idx+1}/{n_chapters}: {heading}")
        logger.info(f"  Blocks: {len(blocks)}")

        translated_blocks = []
        ch_footnotes = 0

        for block in tqdm(blocks, desc=f"  Ch{ch_idx+1}", leave=False):
            content = block.get("content", "")
            if not content or not content.strip():
                translated_blocks.append(block)
                continue

            request = TranslationRequest(
                content_text_id=total_blocks + 1,
                content_source_text=content,
            )

            try:
                response = service.translate(request)
                tac = response.translated_annotated_content

                translated_block = {
                    **block,
                    "translated_content": tac.annotated_content_text,
                    "content_type": tac.content_type,
                    "footnotes": [
                        {
                            "key": fn.footnote_key,
                            "ideogram": fn.footnote_details.footnote_ideogram,
                            "pinyin": fn.footnote_details.footnote_pinyin,
                            "explanation": fn.footnote_details.footnote_explanation,
                        }
                        for fn in tac.content_footnotes
                    ],
                }
                ch_footnotes += len(translated_block["footnotes"])
                translated_blocks.append(translated_block)
            except Exception as e:
                logger.error(f"  Block translation failed: {e}")
                translated_blocks.append(block)

            total_blocks += 1

        # Translate the chapter heading
        try:
            heading_req = TranslationRequest(
                content_text_id=9000 + ch_idx,
                content_source_text=heading,
            )
            heading_resp = service.translate(heading_req)
            translated_title = heading_resp.translated_annotated_content.annotated_content_text
        except Exception:
            translated_title = heading

        translated_chapter = {
            **chapter,
            "translated_title": translated_title,
            "content_blocks": translated_blocks,
        }
        translated_chapters.append(translated_chapter)
        total_footnotes += ch_footnotes
        logger.info(f"  Translated: {len(translated_blocks)} blocks, {ch_footnotes} footnotes")

    elapsed = time.time() - start

    # Build output JSON (only translated chapters)
    output_data = {
        **book_data,
        "meta": {
            **meta,
            "translation": {
                "title": translated_chapters[0].get("translated_title", ""),
                "author": meta.get("author", "Liang Yusheng"),
            },
        },
        "structure": {
            **book_data.get("structure", {}),
            "body": {"chapters": translated_chapters},
        },
    }

    # Save translated JSON
    json_out = OUTPUT_DIR / f"translated_{work_id}_3ch.json"
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    logger.info(f"\nSaved JSON: {json_out}")

    # Build EPUB
    epub_out = OUTPUT_DIR / f"translated_{work_id}_3ch.epub"
    try:
        builder = EpubBuilder()
        builder.build(json_out, epub_out)
        logger.info(f"Saved EPUB: {epub_out}")
    except Exception as e:
        logger.error(f"EPUB build failed: {e}")
        epub_out = None

    return {
        "work_id": work_id,
        "chapters": n_chapters,
        "blocks": total_blocks,
        "footnotes": total_footnotes,
        "time_seconds": round(elapsed, 1),
        "json_path": str(json_out),
        "epub_path": str(epub_out) if epub_out else None,
    }


def main():
    logger.info("DAG Pipeline Validation - Translating 6 Liang Yusheng chapters")
    logger.info(f"Output: {OUTPUT_DIR}")

    # Initialize translation service
    service = TranslationService(
        model="gpt-4.1-nano",
        temperature=0.3,
        max_retries=3,
        timeout=120,
    )

    results = []
    for book in BOOKS:
        result = translate_book_chapters(book, service)
        results.append(result)

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("VALIDATION SUMMARY")
    logger.info(f"{'='*60}")

    total_ch = 0
    total_bl = 0
    total_fn = 0
    total_time = 0

    for r in results:
        logger.info(f"\n  {r['work_id']}:")
        logger.info(f"    Chapters: {r['chapters']}")
        logger.info(f"    Blocks:   {r['blocks']}")
        logger.info(f"    Footnotes:{r['footnotes']}")
        logger.info(f"    Time:     {r['time_seconds']}s")
        logger.info(f"    JSON:     {r['json_path']}")
        logger.info(f"    EPUB:     {r['epub_path']}")
        total_ch += r["chapters"]
        total_bl += r["blocks"]
        total_fn += r["footnotes"]
        total_time += r["time_seconds"]

    logger.info(f"\n  TOTALS:")
    logger.info(f"    Chapters:  {total_ch}")
    logger.info(f"    Blocks:    {total_bl}")
    logger.info(f"    Footnotes: {total_fn}")
    logger.info(f"    Time:      {total_time}s")

    # =========================================================================
    # POST-TRANSLATION VALIDATION
    # =========================================================================
    logger.info(f"\n{'='*60}")
    logger.info("POST-TRANSLATION TEXT & FORMAT VALIDATION")
    logger.info(f"{'='*60}")

    all_passed = True

    for r in results:
        work_id = r["work_id"]
        json_path = Path(r["json_path"])
        epub_path = Path(r["epub_path"]) if r["epub_path"] else None

        logger.info(f"\n--- {work_id} ---")

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

        for ch_idx, ch in enumerate(chapters):
            ch_num = ch_idx + 1
            heading = ch.get("heading", ch.get("title", ""))
            translated_title = ch.get("translated_title", "")
            blocks = ch.get("content_blocks", [])

            # 1. Heading translated?
            if not translated_title or translated_title == heading:
                logger.warning(f"  Ch{ch_num}: heading NOT translated (still Chinese)")
                all_passed = False
            else:
                logger.info(f"  Ch{ch_num} heading: {translated_title[:60]}")

            # 2. Check blocks have translated_content
            translated_count = 0
            empty_translations = 0
            blocks_with_footnotes = 0
            total_fn_count = 0
            orphan_markers = 0
            missing_markers = 0

            for block in blocks:
                tc = block.get("translated_content", "")
                fns = block.get("footnotes", [])

                if tc:
                    translated_count += 1
                else:
                    empty_translations += 1

                if fns:
                    blocks_with_footnotes += 1
                    total_fn_count += len(fns)

                # 3. Footnote marker integrity: each [N] in text should
                #    have a matching footnote, and vice versa
                if tc and fns:
                    import re
                    markers_in_text = set(int(m) for m in re.findall(r'\[(\d+)\]', tc))
                    fn_keys = set(fn.get("key", 0) for fn in fns)

                    orphans = markers_in_text - fn_keys
                    missing = fn_keys - markers_in_text

                    if orphans:
                        orphan_markers += len(orphans)
                    if missing:
                        missing_markers += len(missing)

            pct = (translated_count / len(blocks) * 100) if blocks else 0
            logger.info(f"    Blocks translated: {translated_count}/{len(blocks)} ({pct:.0f}%)")

            if empty_translations > 0:
                logger.warning(f"    Empty translations: {empty_translations}")
                all_passed = False

            logger.info(f"    Footnotes: {total_fn_count} across {blocks_with_footnotes} blocks")

            if orphan_markers > 0:
                logger.warning(f"    Orphan markers (in text but no footnote): {orphan_markers}")
                all_passed = False
            if missing_markers > 0:
                logger.warning(f"    Missing markers (footnote but not in text): {missing_markers}")
                all_passed = False

            # 4. Sample translation quality - print first block
            first_translated = next(
                (b for b in blocks if b.get("translated_content")), None
            )
            if first_translated:
                sample = first_translated["translated_content"][:200]
                logger.info(f"    Sample: {sample}...")

        # 5. EPUB validation
        if epub_path and epub_path.exists():
            epub_size = epub_path.stat().st_size
            logger.info(f"  EPUB: {epub_path.name} ({epub_size:,} bytes)")

            # Validate EPUB structure
            try:
                from ebooklib import epub as epublib
                book = epublib.read_epub(str(epub_path))
                items = list(book.get_items())
                spine_items = [item for item in book.get_items_of_type(9)]  # XHTML items
                logger.info(f"  EPUB items: {len(items)}, spine chapters: {len(spine_items)}")

                # Check each chapter XHTML for footnotes
                for item in spine_items:
                    content = item.get_content().decode("utf-8", errors="replace")
                    fn_count = content.count('epub:type="footnote"')
                    noteref_count = content.count('epub:type="noteref"')
                    if fn_count > 0 or noteref_count > 0:
                        logger.info(f"    {item.get_name()}: {noteref_count} noterefs, {fn_count} footnotes")

                logger.info(f"  EPUB validation: PASS")
            except Exception as e:
                logger.error(f"  EPUB validation failed: {e}")
                all_passed = False
        else:
            logger.warning(f"  EPUB not generated")
            all_passed = False

    logger.info(f"\n{'='*60}")
    if all_passed:
        logger.info("ALL POST-TRANSLATION VALIDATIONS PASSED")
    else:
        logger.warning("SOME VALIDATIONS HAD WARNINGS - review above")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
