#!/usr/bin/env python3
"""
End-to-end pipeline validation: translate 2 chapters → 4-phase footnote cleanup → validate.

Translates chapters into the nested structure expected by
remove_trivial_footnotes.py, then runs the full 4-phase cleanup pipeline
and validates marker/footnote integrity on the output.

Usage:
    python scripts/test_pipeline_validation.py \
        --input path/to/cleaned.json \
        --start-chapter 4 --num-chapters 2
"""

import sys
import json
import re
import time
import argparse
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "iron_abacus_translator"))

from dotenv import load_dotenv
load_dotenv()

from utils.footnote_context import FootnoteContextAccumulator
from wrappers.content_block_translation_wrapper import ContentBlockTranslationWrapper
from utils.remove_trivial_footnotes import (
    TrivialFootnoteRemover,
    TrivialityConfig,
    validate_footnote_integrity,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

from utils.environment_config import get_or_create_config
CATALOG_DB = get_or_create_config().catalog_path


def _lookup_catalog_metadata(work_number, title_zh="", author_zh=""):
    """Look up curated English title/author/year from the catalog database.

    Tries work_number first, falls back to title match.
    Returns dict with title_en, author_en, publication_year, edition or None.
    """
    if not CATALOG_DB.exists():
        return None

    from utils.db import connect_catalog
    conn = connect_catalog(CATALOG_DB)
    cur = conn.cursor()

    # Try by work_number (strip volume suffix like 'a', 'b')
    wn_base = work_number.rstrip("abcdefgh") if work_number else ""
    row = None
    if wn_base:
        cur.execute("""
            SELECT w.work_number, w.title_chinese, w.author_chinese,
                   w.publication_year,
                   COALESCE(wct.consensus_title_english, w.title_english, '') as title_en,
                   COALESCE(wct.consensus_author_english, w.author_english, '') as author_en
            FROM works w
            LEFT JOIN works_consensus_translations wct ON w.work_id = wct.work_id
            WHERE w.work_number LIKE ?
            LIMIT 1
        """, (wn_base + "%",))
        row = cur.fetchone()

    # Fall back to title match
    if not row and title_zh:
        cur.execute("""
            SELECT w.work_number, w.title_chinese, w.author_chinese,
                   w.publication_year,
                   COALESCE(wct.consensus_title_english, w.title_english, '') as title_en,
                   COALESCE(wct.consensus_author_english, w.author_english, '') as author_en
            FROM works w
            LEFT JOIN works_consensus_translations wct ON w.work_id = wct.work_id
            WHERE w.title_chinese = ?
            LIMIT 1
        """, (title_zh,))
        row = cur.fetchone()

    conn.close()

    if not row:
        return None

    title_en = row[4] or title_zh
    author_en = row[5] or author_zh

    # Detect edition from title
    edition = None
    title_cn = row[1] or ""
    if "新修版" in title_cn:
        edition = "Revised Edition"
    elif "舊版" in title_cn:
        edition = "Original Edition"

    return {
        "title_en": title_en,
        "author_en": author_en,
        "publication_year": row[3],
        "edition": edition,
    }


def _translate_block(wrapper, block, block_idx, content, chapter_num, max_attempts=3):
    """Translate a single block with retries. Returns translated block or None."""
    for attempt in range(max_attempts):
        try:
            result = wrapper.execute(
                content_text_id=block_idx + 1,
                content_source_text=content,
                work_id="TEST",
                chapter_num=chapter_num,
            )
            if result.success:
                annotated = result.translated_data.get("translated_annotated_content", {})
                trans_text = annotated.get("annotated_content_text", "")
                if trans_text.strip():
                    return {
                        **block,
                        "translated_content": trans_text,
                        "footnotes": [
                            {
                                "key": fn["footnote_key"],
                                "ideogram": fn["footnote_details"]["footnote_ideogram"],
                                "pinyin": fn["footnote_details"]["footnote_pinyin"],
                                "explanation": fn["footnote_details"]["footnote_explanation"],
                            }
                            for fn in annotated.get("content_footnotes", [])
                        ],
                        "content_type": annotated.get("content_type", "narrative"),
                    }
                else:
                    logger.warning(f"Block {block_idx+1} empty (attempt {attempt+1}/{max_attempts})")
            else:
                logger.warning(f"Block {block_idx+1} failed (attempt {attempt+1}/{max_attempts}): {result.error}")
        except Exception as e:
            logger.error(f"Block {block_idx+1} error (attempt {attempt+1}/{max_attempts}): {e}")
        if attempt < max_attempts - 1:
            time.sleep(2 * (attempt + 1))
    return None


def consolidate_content_blocks(blocks):
    """Consolidate fragmented content into unified blocks.

    Handles two patterns:
    1. VERSE: Consecutive short lines (< 50 chars) forming poems/songs
    2. QUOTED PASSAGES: Multi-block quoted text (letters, epistles, monologues,
       proclamations) where blocks continue a quoted passage opened with 「/『
       without a closing 」/』 until the final block.

    Returns new block list with consolidated blocks.
    """
    OPEN_QUOTES = set("「『")
    CLOSE_QUOTES = set("」』")
    MAX_VERSE_LINE = 50   # max chars for a line to be considered verse
    MIN_VERSE_RUN = 2     # minimum consecutive lines to form a verse
    VALID_TYPES = {"text", "verse", "paragraph", "narrative", "dialogue",
                   "document", "thought", "descriptive"}

    result = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        content = block.get("content", "").strip()
        btype = block.get("type", "")

        if btype not in VALID_TYPES or not content:
            result.append(block)
            i += 1
            continue

        # --- Pattern 1: Quoted passage (verse, letter, monologue) ---
        # Detect a block that opens a quote but doesn't close it
        starts_with_quote = content and content[0] in OPEN_QUOTES
        ends_with_close = content and content[-1] in CLOSE_QUOTES
        # Also check for 』」 double close (nested quotes)
        if len(content) >= 2 and content[-2:] in ("』」", "」」", "』』"):
            ends_with_close = True

        if starts_with_quote and not ends_with_close:
            # Look ahead for blocks that continue this quoted passage
            run = [i]
            j = i + 1
            while j < len(blocks):
                nb = blocks[j]
                nc = nb.get("content", "").strip()
                nt = nb.get("type", "")

                if nt not in VALID_TYPES or not nc:
                    break

                run.append(j)

                # Check if this block closes the quoted passage
                if nc and nc[-1] in CLOSE_QUOTES:
                    break
                if len(nc) >= 2 and nc[-2:] in ("』」", "」」", "』』"):
                    break

                j += 1
            else:
                j = len(blocks)

            if len(run) >= 2:
                # Determine type: short lines = verse, long lines = document
                avg_len = sum(
                    len(blocks[idx].get("content", "").strip()) for idx in run
                ) / len(run)
                all_short = all(
                    len(blocks[idx].get("content", "").strip()) <= MAX_VERSE_LINE
                    for idx in run
                )

                if all_short:
                    merge_type = "verse"
                    separator = "\n"
                    label = "verse"
                else:
                    merge_type = "document"
                    separator = "\n\n"
                    label = "quoted passage"

                merged_content = separator.join(
                    blocks[idx].get("content", "").strip() for idx in run
                )
                merged_block = {
                    **blocks[run[0]],
                    "content": merged_content,
                    "type": merge_type,
                    "_consolidated": True,
                    "_consolidated_type": label,
                    "_original_block_ids": [blocks[idx].get("id", "") for idx in run],
                }
                result.append(merged_block)
                logger.info(
                    f"  Consolidated {len(run)} {label} lines into 1 block "
                    f"({blocks[run[0]].get('id', '')} - {blocks[run[-1]].get('id', '')})"
                )
                i = run[-1] + 1
                continue

        # --- Pattern 2: Consecutive short lines (unquoted verse) ---
        if len(content) <= MAX_VERSE_LINE:
            run = [i]
            j = i + 1
            while j < len(blocks):
                nb = blocks[j]
                nc = nb.get("content", "").strip()
                nt = nb.get("type", "")
                if nt in VALID_TYPES and nc and len(nc) <= MAX_VERSE_LINE:
                    run.append(j)
                    j += 1
                else:
                    break

            if len(run) >= MIN_VERSE_RUN:
                merged_content = "\n".join(
                    blocks[idx].get("content", "").strip() for idx in run
                )
                merged_block = {
                    **blocks[run[0]],
                    "content": merged_content,
                    "type": "verse",
                    "_consolidated": True,
                    "_consolidated_type": "verse",
                    "_original_block_ids": [blocks[idx].get("id", "") for idx in run],
                }
                result.append(merged_block)
                logger.info(
                    f"  Consolidated {len(run)} verse lines into 1 block "
                    f"({blocks[run[0]].get('id', '')} - {blocks[run[-1]].get('id', '')})"
                )
                i = j
                continue

        result.append(block)
        i += 1

    return result


def translate_chapters(book_data, start_ch, num_chapters, model, max_workers=6):
    """Translate chapters with parallel workers."""
    chapters = book_data.get("structure", {}).get("body", {}).get("chapters", [])
    end_ch = min(start_ch + num_chapters, len(chapters))
    selected = chapters[start_ch:end_ch]

    logger.info(f"Translating chapters {start_ch+1}-{end_ch} ({len(selected)} chapters, {max_workers} workers)")

    accumulator = FootnoteContextAccumulator()
    wrapper = ContentBlockTranslationWrapper(
        accumulator=accumulator,
        model=model,
        temperature=0.3,
        max_retries=2,
        timeout=120,
    )

    translatable_types = {
        "text", "paragraph", "narrative", "dialogue", "verse",
        "document", "thought", "descriptive",
    }

    # Collect all translatable blocks across chapters
    all_jobs = []  # (ch_idx, block_idx, block, content, chapter_num)
    chapter_blocks = []  # per-chapter list of blocks (with placeholders)

    for ch_idx, ch in enumerate(selected):
        blocks = ch.get("content_blocks", [])
        # Consolidate verse/quoted passages before translation
        blocks = consolidate_content_blocks(blocks)
        block_list = [None] * len(blocks)

        for block_idx, block in enumerate(blocks):
            btype = block.get("type", "")
            content = block.get("content", "").strip()

            if btype not in translatable_types or not content:
                block_list[block_idx] = block  # keep as-is
            else:
                all_jobs.append((ch_idx, block_idx, block, content, start_ch + ch_idx + 1))

        chapter_blocks.append((ch, block_list))

    total_jobs = len(all_jobs)
    logger.info(f"Total translatable blocks: {total_jobs}")

    # --- Pass 1: parallel translation ---
    completed = 0
    failed_blocks = []
    lock = threading.Lock()

    def do_translate(job):
        ch_idx, block_idx, block, content, chapter_num = job
        return (ch_idx, block_idx, block, _translate_block(
            wrapper, block, block_idx, content, chapter_num,
        ))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(do_translate, job): job for job in all_jobs}

        for future in as_completed(futures):
            ch_idx, block_idx, block, block_out = future.result()
            ch_data, block_list = chapter_blocks[ch_idx]

            if block_out:
                block_list[block_idx] = block_out
            else:
                block["_failed"] = True
                block_list[block_idx] = block
                failed_blocks.append((ch_idx, block_idx, block.get("id", "?")))

            with lock:
                completed += 1
                if completed % 20 == 0 or completed == total_jobs:
                    logger.info(f"  Progress: {completed}/{total_jobs} blocks done")

    # Build translated chapters
    translated_chapters = []
    for ch_idx, (ch, block_list) in enumerate(chapter_blocks):
        ch_dict = {**ch, "content_blocks": block_list}
        # Use first block's translated_content as the English chapter title
        if block_list and block_list[0] and block_list[0].get("translated_content"):
            ch_dict["translated_title"] = block_list[0]["translated_content"].strip()
        translated_chapters.append(ch_dict)
        translated_count = sum(1 for b in block_list if b and b.get("translated_content"))
        total = len(block_list)
        logger.info(f"  Chapter {start_ch + ch_idx + 1}: {translated_count}/{total} blocks translated")

    # --- Pass 2+: retry failed blocks (sequential) ---
    repass = 1
    while failed_blocks:
        repass += 1
        logger.info(f"Repass {repass}: retrying {len(failed_blocks)} failed blocks (waiting 10s)...")
        time.sleep(10)

        still_failed = []
        for ch_idx, block_idx, block_id in failed_blocks:
            ch_blocks = translated_chapters[ch_idx]["content_blocks"]
            block = ch_blocks[block_idx]
            content = block.get("content", "").strip()

            block_out = _translate_block(
                wrapper, block, block_idx, content,
                start_ch + ch_idx + 1, max_attempts=3,
            )
            if block_out:
                ch_blocks[block_idx] = block_out
                logger.info(f"  Repass {repass}: {block_id} succeeded")
            else:
                still_failed.append((ch_idx, block_idx, block_id))
                logger.warning(f"  Repass {repass}: {block_id} still failing")

        failed_blocks = still_failed

        if repass >= 5:
            logger.error(f"Giving up on {len(failed_blocks)} blocks after {repass} passes:")
            for _, _, bid in failed_blocks:
                logger.error(f"  {bid}")
            break

    return translated_chapters


def count_footnotes(chapters):
    """Count total footnotes across chapters."""
    return sum(
        len(block.get("footnotes", []))
        for ch in chapters
        for block in ch.get("content_blocks", [])
    )


def detailed_validation(data):
    """Run detailed validation and print results."""
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

    issues = []
    translatable_types = {
        "text", "paragraph", "narrative", "dialogue", "verse",
        "document", "thought", "descriptive",
    }
    stats = {
        "blocks_with_translation": 0,
        "blocks_untranslated": 0,
        "blocks_with_footnotes": 0,
        "total_footnotes": 0,
        "orphan_marker_blocks": 0,
        "non_sequential_blocks": 0,
        "empty_explanation_fns": 0,
        "duplicate_ideograms_in_block": 0,
    }

    for ch_idx, ch in enumerate(chapters):
        # Collect all footnote keys across the chapter for continuity check
        chapter_fn_keys = []

        for block in ch.get("content_blocks", []):
            block_id = block.get("id", "unknown")
            text = block.get("translated_content", "")
            fns = block.get("footnotes", [])
            btype = block.get("type", "")
            has_source = bool(block.get("content", "").strip())

            if text:
                stats["blocks_with_translation"] += 1
            elif btype in translatable_types and has_source:
                stats["blocks_untranslated"] += 1
                issues.append(f"{block_id}: UNTRANSLATED ({btype}, {len(block.get('content',''))} chars)")
            if fns:
                stats["blocks_with_footnotes"] += 1
                stats["total_footnotes"] += len(fns)

            # Collect keys for chapter-level continuity check
            for fn in fns:
                chapter_fn_keys.append((fn.get("key"), block_id))

            # Check orphan markers (marker in text with no matching footnote)
            markers = set(re.findall(r"\[(\d+)\]", text))
            fn_keys = {str(fn.get("key")) for fn in fns}
            orphans = markers - fn_keys
            if orphans:
                stats["orphan_marker_blocks"] += 1
                issues.append(f"{block_id}: orphan markers {sorted(orphans)}")

            # Check empty explanations
            for fn in fns:
                if not fn.get("explanation", "").strip():
                    stats["empty_explanation_fns"] += 1

            # Check duplicate ideograms within block
            ideograms = [fn.get("ideogram", "") for fn in fns]
            if len(ideograms) != len(set(ideograms)):
                stats["duplicate_ideograms_in_block"] += 1

        # Chapter-level: check footnote keys are sequential 1..N
        if chapter_fn_keys:
            actual_keys = [k for k, _ in chapter_fn_keys]
            expected_keys = list(range(1, len(actual_keys) + 1))
            if actual_keys != expected_keys:
                stats["non_sequential_blocks"] += 1
                issues.append(
                    f"ch{ch_idx+1}: chapter-level keys {actual_keys} != expected {expected_keys}"
                )

    return stats, issues


def print_sample_footnotes(data, label, max_samples=15):
    """Print sample footnotes for quality review."""
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
    all_fns = []
    for ch in chapters:
        for block in ch.get("content_blocks", []):
            for fn in block.get("footnotes", []):
                all_fns.append(fn)

    print(f"\n{'='*70}")
    print(f" {label} — {len(all_fns)} footnotes total")
    print(f"{'='*70}")

    if not all_fns:
        print("  (none)")
        return

    # Show evenly spaced samples
    step = max(1, len(all_fns) // max_samples)
    samples = all_fns[::step][:max_samples]
    for fn in samples:
        ideo = fn.get("ideogram", "?")
        expl = fn.get("explanation", "")[:90]
        print(f"  {ideo}: {expl}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument("--start-chapter", "-s", type=int, default=4, help="1-indexed start chapter")
    parser.add_argument("--num-chapters", "-n", type=int, default=2)
    parser.add_argument("--model", default="gpt-4.1-nano")
    parser.add_argument("--output-dir", default="translation_data/pipeline_validation")
    parser.add_argument("--workers", "-w", type=int, default=6, help="Parallel translation workers")
    args = parser.parse_args()

    input_file = Path(args.input)
    with open(input_file) as f:
        book_data = json.load(f)

    work_title = book_data.get("meta", {}).get("title", input_file.stem)
    start_idx = args.start_chapter - 1  # convert to 0-indexed

    # ── Step 1: Translate ──
    print(f"\n{'='*70}")
    print(f" STEP 1: TRANSLATE — {work_title}")
    print(f" Chapters {args.start_chapter}-{args.start_chapter + args.num_chapters - 1}")
    print(f"{'='*70}")

    t0 = time.time()
    translated_chapters = translate_chapters(book_data, start_idx, args.num_chapters, args.model, max_workers=args.workers)
    translate_time = time.time() - t0

    fn_count_raw = count_footnotes(translated_chapters)
    print(f"\n  Translation done in {translate_time:.0f}s")
    print(f"  Raw footnotes generated: {fn_count_raw}")

    # Look up revised metadata from catalog DB
    meta = dict(book_data.get("meta", {}))
    meta.setdefault("translation", {})
    title_zh = meta.get("title", "")
    author_zh = meta.get("author", meta.get("author_chinese", ""))
    work_number = meta.get("work_number", "")

    # Try to get curated title/author/year from the catalog database
    db_meta = _lookup_catalog_metadata(work_number, title_zh, author_zh)
    if db_meta:
        meta["translation"]["title"] = db_meta["title_en"]
        meta["translation"]["author"] = db_meta["author_en"]
        if db_meta.get("publication_year"):
            meta["translation"]["publication_year"] = db_meta["publication_year"]
        if db_meta.get("edition"):
            meta["translation"]["edition"] = db_meta["edition"]
        pub_year = db_meta.get("publication_year", "")
        year_str = f" ({pub_year})" if pub_year else ""
        logger.info(
            f"  Metadata from DB: {meta['translation']['title']} "
            f"by {meta['translation']['author']}{year_str}"
        )
    else:
        # Fallback: use Chinese as-is
        meta["translation"]["title"] = title_zh
        meta["translation"]["author"] = author_zh
        logger.warning(f"  No DB metadata found for {work_number}, using Chinese titles")

    # Build work-like structure for the cleanup pipeline
    work_data = {
        "meta": meta,
        "structure": {
            "body": {
                "chapters": translated_chapters,
            }
        },
    }

    # Save raw translated output
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = input_file.stem.replace("cleaned_", "")
    raw_path = out_dir / f"{stem}_ch{args.start_chapter}-{args.start_chapter + args.num_chapters - 1}_raw.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(work_data, f, ensure_ascii=False, indent=2)
    print(f"  Raw output: {raw_path}")

    # Pre-cleanup validation
    stats_raw, issues_raw = detailed_validation(work_data)
    print(f"\n  PRE-CLEANUP VALIDATION:")
    for k, v in stats_raw.items():
        print(f"    {k}: {v}")
    if issues_raw:
        print(f"    Issues: {len(issues_raw)}")
        for iss in issues_raw[:5]:
            print(f"      - {iss}")

    print_sample_footnotes(work_data, "RAW FOOTNOTES (before cleanup)")

    # ── Step 2: 4-Phase Footnote Cleanup ──
    print(f"\n{'='*70}")
    print(f" STEP 2: 4-PHASE FOOTNOTE CLEANUP")
    print(f"{'='*70}")

    cleaned_path = out_dir / f"{stem}_ch{args.start_chapter}-{args.start_chapter + args.num_chapters - 1}_cleaned.json"

    config = TrivialityConfig(
        model="gpt-4.1-nano",  # Always use nano for cleanup (cheap scoring)
        batch_size=25,
        create_backup=False,
    )
    remover = TrivialFootnoteRemover(config)

    t1 = time.time()
    result = remover.process_file(raw_path, cleaned_path)
    cleanup_time = time.time() - t1

    print(f"\n  Cleanup done in {cleanup_time:.0f}s")
    print(f"  Total footnotes:  {result.total_footnotes}")
    print(f"  Removed:          {result.removed_count}")
    print(f"  Preserved:        {result.preserved_count}")
    print(f"  Duplicates:       {result.duplicate_count}")
    print(f"  Validation:       {'PASSED' if result.validation_passed else 'FAILED'}")

    if not result.validation_passed:
        print("\n  *** VALIDATION FAILED — check logs ***")
        return 1

    # ── Step 3: Post-Cleanup Validation ──
    print(f"\n{'='*70}")
    print(f" STEP 3: POST-CLEANUP VALIDATION")
    print(f"{'='*70}")

    with open(cleaned_path) as f:
        cleaned_data = json.load(f)

    stats_clean, issues_clean = detailed_validation(cleaned_data)
    print(f"\n  POST-CLEANUP STATS:")
    for k, v in stats_clean.items():
        print(f"    {k}: {v}")
    if issues_clean:
        print(f"    Issues: {len(issues_clean)}")
        for iss in issues_clean[:10]:
            print(f"      - {iss}")
    else:
        print(f"    Issues: 0 — ALL CLEAN")

    # Built-in validation
    integrity = validate_footnote_integrity(cleaned_data)
    print(f"\n  INTEGRITY CHECK: {'PASSED' if integrity['passed'] else 'FAILED'}")
    if not integrity["passed"]:
        for err in integrity["errors"][:10]:
            print(f"    - {err}")

    print_sample_footnotes(cleaned_data, "SURVIVING FOOTNOTES (after cleanup)")

    # ── Summary ──
    fn_final = stats_clean["total_footnotes"]
    removed_pct = (fn_count_raw - fn_final) / fn_count_raw * 100 if fn_count_raw else 0

    print(f"\n{'='*70}")
    print(f" SUMMARY")
    print(f"{'='*70}")
    print(f"  Work:             {work_title}")
    print(f"  Chapters:         {args.start_chapter}-{args.start_chapter + args.num_chapters - 1}")
    print(f"  Translate time:   {translate_time:.0f}s")
    print(f"  Cleanup time:     {cleanup_time:.0f}s")
    print(f"  Total time:       {translate_time + cleanup_time:.0f}s")
    print(f"  Raw footnotes:    {fn_count_raw}")
    print(f"  Final footnotes:  {fn_final}")
    print(f"  Removed:          {fn_count_raw - fn_final} ({removed_pct:.0f}%)")
    print(f"  Validation:       {'ALL PASSED' if not issues_clean and integrity['passed'] else 'ISSUES FOUND'}")
    print(f"  Orphan markers:   {stats_clean['orphan_marker_blocks']}")
    print(f"  Non-sequential:   {stats_clean['non_sequential_blocks']}")
    print(f"  Raw output:       {raw_path}")
    print(f"  Cleaned output:   {cleaned_path}")

    # Removal breakdown by type
    type_counts = {}
    for rf in result.removed_footnotes:
        t = rf.get("type", "UNKNOWN")
        type_counts[t] = type_counts.get(t, 0) + 1
    if type_counts:
        print(f"\n  REMOVAL BREAKDOWN:")
        for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"    {t}: {c}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
