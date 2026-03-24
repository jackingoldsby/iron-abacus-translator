#!/usr/bin/env python3
"""
Per-Chapter Footnote Renumbering for EPUB

Current translated JSON has per-block footnotes [1], [2], [3]...
For EPUB popup links, renumber per-chapter: Chapter 1 gets [1] through [N],
Chapter 2 restarts at [1].

Usage:
    from utils.epub_footnote_renumber import renumber_footnotes_per_chapter

    data, chapter_map = renumber_footnotes_per_chapter(data)
"""

import re
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


def renumber_footnotes_per_chapter(
    data: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[int, List[Dict[str, Any]]]]:
    """
    Renumber footnotes per-chapter for EPUB anchor linking.

    Walks blocks in chapter order, assigns sequential keys within each chapter.
    Remaps [old] -> [new] in translated_content. Generates epub_footnote_id
    per footnote: fn-ch{N}-{M} for anchor linking.

    Args:
        data: Full work JSON data with structure.body.chapters

    Returns:
        Tuple of (modified_data, chapter_footnote_map)
        chapter_footnote_map: {chapter_index: [footnote_dicts_with_epub_ids]}
    """
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
    chapter_footnote_map: Dict[int, List[Dict[str, Any]]] = {}

    for ch_idx, chapter in enumerate(chapters):
        chapter_num = ch_idx + 1
        chapter_counter = 0
        chapter_footnotes: List[Dict[str, Any]] = []

        for block in chapter.get("content_blocks", []):
            footnotes = block.get("footnotes", [])
            if not footnotes:
                continue

            translated = block.get("translated_content", "")
            old_to_new: Dict[int, int] = {}

            for fn in footnotes:
                old_key = fn.get("key")
                chapter_counter += 1
                new_key = chapter_counter

                old_to_new[old_key] = new_key
                fn["key"] = new_key
                fn["epub_footnote_id"] = f"fn-ch{chapter_num}-{new_key}"

                chapter_footnotes.append({
                    "epub_footnote_id": fn["epub_footnote_id"],
                    "key": new_key,
                    "ideogram": fn.get("ideogram", ""),
                    "pinyin": fn.get("pinyin", ""),
                    "explanation": fn.get("explanation", ""),
                    "block_id": block.get("id", ""),
                })

            # Remap inline markers in translated content
            if translated and old_to_new:
                block["translated_content"] = _remap_markers(
                    translated, old_to_new
                )

        chapter_footnote_map[chapter_num] = chapter_footnotes

        logger.info(
            f"Chapter {chapter_num}: renumbered {chapter_counter} footnotes"
        )

    total = sum(len(fns) for fns in chapter_footnote_map.values())
    logger.info(
        f"Renumbered {total} footnotes across {len(chapters)} chapters"
    )

    return data, chapter_footnote_map


def _remap_markers(text: str, old_to_new: Dict[int, int]) -> str:
    """Remap inline footnote markers [N] based on old->new key mapping."""

    def replace_marker(match):
        old_key = int(match.group(1))
        new_key = old_to_new.get(old_key)
        if new_key is not None:
            return f"[{new_key}]"
        return match.group(0)

    return re.sub(r"\[(\d+)\]", replace_marker, text)


def main():
    """CLI entry point for testing."""
    import json
    import sys
    from pathlib import Path

    if len(sys.argv) < 2:
        print("Usage: python utils/epub_footnote_renumber.py <input.json> [output.json]")
        return 1

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data, chapter_map = renumber_footnotes_per_chapter(data)

    # Print summary
    for ch_num, footnotes in sorted(chapter_map.items()):
        print(f"Chapter {ch_num}: {len(footnotes)} footnotes")

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\nWrote renumbered output to: {output_path}")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    exit(main())
