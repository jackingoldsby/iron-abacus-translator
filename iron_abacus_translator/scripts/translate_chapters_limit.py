#!/usr/bin/env python3
"""
Translate a limited number of chapters from a cleaned book JSON file.

Uses ContentBlockTranslationWrapper (latest prompts, suppress list, cross-block dedup).
Translates metadata (title, author), chapter titles, and body content blocks.

Usage:
    python scripts/translate_chapters_limit.py --input path/to/cleaned.json --chapters 3
    python scripts/translate_chapters_limit.py --input path/to/cleaned.json --chapters 5 --output path/to/output.json
"""

import sys
import json
import argparse
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from wrappers.content_block_translation_wrapper import ContentBlockTranslationWrapper
from utils.footnote_context import FootnoteContextAccumulator
from utils.clients import get_llm_client, LLMRequest
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = "translation_data/test_translations/"


def parse_args():
    """Parse command-line arguments for chapter-limited translation."""
    parser = argparse.ArgumentParser(description="Translate a limited number of chapters from a cleaned book JSON.")
    parser.add_argument("--input", "-i", required=True, help="Path to cleaned book JSON file")
    parser.add_argument("--chapters", "-c", type=int, default=3, help="Number of chapters to translate (default: 3)")
    parser.add_argument("--output", "-o", help="Output path (auto-generated if not specified)")
    parser.add_argument("--model", default="gpt-4.1-mini", help="Model to use (default: gpt-4.1-mini)")
    return parser.parse_args()


def translate_text(llm, text: str, context: str = "") -> str:
    """Translate a short Chinese text to English (no footnotes)."""
    if not text or not text.strip():
        return ""
    prompt = (
        "Translate the following Classical Chinese text to English. "
        "Return ONLY the English translation, no explanation or formatting.\n"
    )
    if context:
        prompt += f"Context: {context}\n"
    prompt += f"\nText: {text}"

    resp = llm.chat(LLMRequest(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        timeout=30,
    ))
    return resp.text.strip().strip('"').strip("'")


def translate_metadata(llm, meta: dict) -> dict:
    """Translate book metadata (title, author) and store under meta.translation."""
    title_zh = meta.get("title", "")
    author_zh = meta.get("author", "")

    title_en = translate_text(llm, title_zh, context="This is a wuxia novel title")
    author_en = translate_text(llm, author_zh, context="This is a Chinese author's name. Transliterate to pinyin with tone marks.")

    logger.info(f"  Title: {title_zh} → {title_en}")
    logger.info(f"  Author: {author_zh} → {author_en}")

    return {
        **meta,
        "translation": {
            "title": title_en,
            "author": author_en,
        },
    }


def translate_chapter_title(llm, title_zh: str, chapter_num: int) -> str:
    """Translate a single chapter title."""
    if not title_zh:
        return f"Chapter {chapter_num}"
    title_en = translate_text(
        llm, title_zh,
        context="This is a wuxia novel chapter title. Translate the descriptive part; convert 第N回/章 to 'Chapter N'."
    )
    return title_en


def main():
    """Translate a limited number of chapters with footnotes and save output."""
    args = parse_args()

    input_file = Path(args.input)
    if not input_file.exists():
        logger.error(f"Input file not found: {input_file}")
        return 1

    # Auto-generate output path if not specified
    if args.output:
        output_file = Path(args.output)
    else:
        stem = input_file.stem.replace("cleaned_", "translated_")
        output_file = Path(DEFAULT_OUTPUT_DIR) / f"{stem}_first_{args.chapters}_chapters.json"

    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Load book
    logger.info(f"Loading book from {input_file}")
    with open(input_file) as f:
        book_data = json.load(f)

    # Extract work_id from metadata if available
    meta = book_data.get("meta", book_data.get("metadata", {}))
    work_id = meta.get("work_number", "unknown")

    # Get chapters
    chapters = book_data.get('structure', {}).get('body', {}).get('chapters', [])
    logger.info(f"Found {len(chapters)} total chapters")

    # Limit chapters
    chapters_to_translate = chapters[:args.chapters]
    logger.info(f"Translating first {len(chapters_to_translate)} chapters")

    # Initialize LLM client (shared for metadata/titles)
    llm = get_llm_client(component="translator", model=args.model)

    # --- Stage 1: Translate metadata ---
    logger.info("Translating metadata...")
    translated_meta = translate_metadata(llm, meta)

    # --- Stage 2: Translate chapter titles ---
    logger.info("Translating chapter titles...")
    for i, chapter in enumerate(chapters_to_translate):
        title_zh = chapter.get("title", "")
        chapter["translated_title"] = translate_chapter_title(llm, title_zh, i + 1)
        logger.info(f"  {title_zh} → {chapter['translated_title']}")

    # --- Stage 3: Translate body content blocks ---
    logger.info("Translating body content...")
    accumulator = FootnoteContextAccumulator()
    wrapper = ContentBlockTranslationWrapper(
        accumulator=accumulator,
        model=args.model,
        temperature=0.3,
        max_retries=3,
        timeout=120,
        llm_client=llm,
    )

    from tqdm import tqdm
    translated_chapters = []

    for i, chapter in enumerate(tqdm(chapters_to_translate, desc="Translating chapters")):
        chapter_num = i + 1
        logger.info(f"\nChapter {chapter_num}/{len(chapters_to_translate)}: {chapter.get('title', 'Untitled')}")
        logger.info(f"  Blocks: {len(chapter.get('content_blocks', []))}")

        translated_blocks = []
        blocks = chapter.get('content_blocks', [])

        for block_idx, block in enumerate(tqdm(blocks, desc=f"  {chapter.get('title', 'Untitled')[:40]}", leave=False)):
            source_text = block.get('content', '')
            if not source_text or len(source_text.strip()) < 5:
                translated_blocks.append(block)
                continue

            result = wrapper.execute(
                content_text_id=block_idx + 1,
                content_source_text=source_text,
                work_id=work_id,
                chapter_num=chapter_num,
            )

            if result.success and result.translated_data:
                annotated = result.translated_data["translated_annotated_content"]
                footnotes = [
                    {
                        "key": fn["footnote_key"],
                        "ideogram": fn["footnote_details"]["footnote_ideogram"],
                        "pinyin": fn["footnote_details"]["footnote_pinyin"],
                        "explanation": fn["footnote_details"]["footnote_explanation"],
                    }
                    for fn in annotated["content_footnotes"]
                ]
                translated_block = {
                    **block,
                    'translated_content': annotated["annotated_content_text"],
                    'footnotes': footnotes,
                    'content_type': annotated.get("content_type", "narrative"),
                }
                translated_blocks.append(translated_block)
            else:
                logger.error(f"Failed to translate block {block_idx+1}: {result.error}")
                translated_blocks.append(block)

        translated_chapter = {
            **chapter,
            'content_blocks': translated_blocks
        }
        translated_chapters.append(translated_chapter)

    # --- Build output with translated metadata and TOC ---
    output_data = {
        **book_data,
        'meta': translated_meta,
        'structure': {
            **book_data['structure'],
            'body': {
                'chapters': translated_chapters
            }
        }
    }

    # Build TOC from translated chapter titles
    toc_entries = []
    for i, ch in enumerate(translated_chapters):
        toc_entries.append({
            "title": ch.get("translated_title", f"Chapter {i+1}"),
            "title_zh": ch.get("title", ""),
            "chapter_number": i + 1,
        })
    output_data["structure"]["table_of_contents"] = toc_entries

    # Save
    logger.info(f"\nSaving to {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    logger.info(f"Translated {len(translated_chapters)} chapters successfully")
    logger.info(f"Output: {output_file}")

    # Summary
    total_blocks = sum(len(ch.get('content_blocks', [])) for ch in translated_chapters)
    total_footnotes = sum(
        len(block.get('footnotes', []))
        for ch in translated_chapters
        for block in ch.get('content_blocks', [])
    )
    logger.info(f"Total blocks translated: {total_blocks}")
    logger.info(f"Total footnotes generated: {total_footnotes}")
    logger.info(f"Unique terms in accumulator: {accumulator.total_registered}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
