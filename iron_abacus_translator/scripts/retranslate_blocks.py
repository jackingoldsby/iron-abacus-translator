#!/usr/bin/env python3
"""
Re-translate specific content blocks (by content_type) in an already-translated JSON.

Usage:
    python scripts/retranslate_blocks.py D60 --content-type verse
    python scripts/retranslate_blocks.py D438 --content-type verse
    python scripts/retranslate_blocks.py D438 --content-type verse --dry-run
"""

import argparse
import glob
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from wrappers.content_block_translation_wrapper import ContentBlockTranslationWrapper
from utils.footnote_context import FootnoteContextAccumulator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

TRANSLATED_DIR = Path("/Users/jacki/project_files/translation_project/translated")


def find_translated_json(work_id: str) -> Path:
    """Find the translated JSON for a work ID."""
    work_dir = TRANSLATED_DIR / work_id
    if not work_dir.exists():
        raise FileNotFoundError(f"No translated directory for {work_id}")
    jsons = list(work_dir.glob("translated_*.json"))
    if not jsons:
        raise FileNotFoundError(f"No translated JSON in {work_dir}")
    if len(jsons) > 1:
        logger.warning(f"Multiple JSONs found, using first: {jsons[0].name}")
    return jsons[0]


def collect_target_blocks(data, content_type: str):
    """
    Yield (chapter_idx, block_idx, block) for blocks matching content_type.
    """
    chapters = data["structure"]["body"]["chapters"]
    for ch_idx, chapter in enumerate(chapters):
        for blk_idx, block in enumerate(chapter.get("content_blocks", [])):
            if block.get("content_type") == content_type:
                yield ch_idx, blk_idx, block


def retranslate(work_id: str, content_type: str, provider: str = "deepseek", dry_run: bool = False):
    json_path = find_translated_json(work_id)
    logger.info(f"Loading {json_path.name}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    targets = list(collect_target_blocks(data, content_type))
    logger.info(f"Found {len(targets)} '{content_type}' blocks to re-translate")

    if not targets:
        logger.info("Nothing to do.")
        return

    for ch_idx, blk_idx, block in targets:
        ch_title = data["structure"]["body"]["chapters"][ch_idx].get("title", "?")
        # Use original_content if present (already-translated block), else content
        source = block.get("original_content") or block.get("content", "")
        logger.info(
            f"  ch{ch_idx + 1} ({ch_title}) block {block.get('id', blk_idx)}: "
            f"{source[:60]}..."
        )

    if dry_run:
        logger.info("Dry run — stopping here.")
        return

    # Set up translation wrapper with specified provider
    from utils.clients import get_llm_client
    accumulator = FootnoteContextAccumulator()
    llm_client = get_llm_client(component="translator", provider=provider)
    wrapper = ContentBlockTranslationWrapper(accumulator=accumulator, llm_client=llm_client)

    success = 0
    failed = 0

    for ch_idx, blk_idx, block in targets:
        block_id = block.get("id", f"block_{blk_idx}")
        source = block.get("original_content") or block.get("content", "")

        logger.info(f"Translating {block_id}...")
        result = wrapper.execute(
            content_text_id=blk_idx + 1,
            content_source_text=source,
            work_id=work_id,
            chapter_num=ch_idx + 1,
        )

        if not result.success:
            logger.error(f"  FAILED: {result.error}")
            failed += 1
            continue

        td = result.translated_data
        ann = td["translated_annotated_content"]

        # Update block in place
        block["translated_content"] = ann["annotated_content_text"]
        block["content_type"] = ann["content_type"]
        block["footnotes"] = [
            {
                "key": fn["footnote_key"],
                "ideogram": fn["footnote_details"]["footnote_ideogram"],
                "pinyin": fn["footnote_details"]["footnote_pinyin"],
                "explanation": fn["footnote_details"]["footnote_explanation"],
            }
            for fn in ann["content_footnotes"]
        ]
        # Ensure original_content is preserved
        if "original_content" not in block:
            block["original_content"] = block.pop("content", source)

        success += 1
        logger.info(
            f"  OK — {len(block['footnotes'])} footnotes, "
            f"type={block['content_type']}"
        )
        time.sleep(0.3)

    logger.info(f"Done: {success} succeeded, {failed} failed out of {len(targets)}")

    if success > 0:
        # Write back
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {json_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Re-translate blocks by content_type in a translated JSON"
    )
    parser.add_argument("work_id", help="Work ID (e.g. D60, D438)")
    parser.add_argument(
        "--content-type", required=True,
        help="Content type to re-translate (e.g. verse, document)"
    )
    parser.add_argument(
        "--provider", default="deepseek",
        help="LLM provider (default: deepseek)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List matching blocks without translating"
    )
    args = parser.parse_args()
    retranslate(args.work_id, args.content_type, args.provider, args.dry_run)


if __name__ == "__main__":
    main()
