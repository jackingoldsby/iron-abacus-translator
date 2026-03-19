#!/usr/bin/env python3
"""
Footnote Density Validator

Standalone validator that checks footnote density per block after translation.
Can trim excess footnotes and renumber remaining ones.

Does NOT modify existing wrappers or TranslationConfig.

Usage:
    from utils.footnote_density_validator import validate_density, trim_excess_footnotes

    result = validate_density(block_data)
    if not result["passed"]:
        block_data = trim_excess_footnotes(block_data)
"""

import re
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default density limits by content type.
# These are soft maximums -- callers can override per block or globally.
# Verse/document get higher limits because classical Chinese poetry and
# formal documents are dense with cultural allusions, place names, and
# historical references that genuinely need annotation.
DEFAULT_LIMITS = {
    "narrative": 8,
    "dialogue": 3,
    "verse": 12,
    "document": 10,
    "descriptive": 6,
    "thought": 3,
}

DEFAULT_MAX = 8  # Fallback for unknown content types


def validate_density(
    block_data: Dict[str, Any],
    max_footnotes: Optional[int] = None,
    limits: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """
    Validate footnote density for a single content block.

    Args:
        block_data: A content block dict with 'footnotes' and optionally 'content_type'
        max_footnotes: Override max footnotes (ignores content_type-based limits)
        limits: Custom limits dict mapping content_type -> max_count

    Returns:
        Dict with keys:
        - passed (bool): Whether density is within limits
        - footnote_count (int): Current number of footnotes
        - limit (int): The applicable limit
        - content_type (str): Detected content type
        - excess_count (int): How many over the limit (0 if passed)
    """
    footnotes = block_data.get("footnotes", [])
    content_type = block_data.get("content_type", "narrative")
    count = len(footnotes)

    if max_footnotes is not None:
        limit = max_footnotes
    else:
        type_limits = limits or DEFAULT_LIMITS
        limit = type_limits.get(content_type, DEFAULT_MAX)

    excess = max(0, count - limit)

    return {
        "passed": excess == 0,
        "footnote_count": count,
        "limit": limit,
        "content_type": content_type,
        "excess_count": excess,
    }


def trim_excess_footnotes(
    block_data: Dict[str, Any],
    max_footnotes: Optional[int] = None,
    limits: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """
    Trim excess footnotes from a block, keeping the first N and renumbering.

    Modifies the block in-place and returns it. Also updates inline markers
    in 'translated_content' to match the new numbering.

    Args:
        block_data: Content block dict to trim
        max_footnotes: Override max footnotes
        limits: Custom limits dict

    Returns:
        The modified block_data (also modified in-place)
    """
    footnotes = block_data.get("footnotes", [])
    content_type = block_data.get("content_type", "narrative")

    if max_footnotes is not None:
        limit = max_footnotes
    else:
        type_limits = limits or DEFAULT_LIMITS
        limit = type_limits.get(content_type, DEFAULT_MAX)

    if len(footnotes) <= limit:
        return block_data

    removed_count = len(footnotes) - limit
    removed_keys = {fn.get("key") for fn in footnotes[limit:]}
    kept_footnotes = footnotes[:limit]

    logger.info(
        f"Trimming block {block_data.get('id', '?')}: "
        f"{len(footnotes)} -> {limit} footnotes "
        f"(removed {removed_count}, content_type={content_type})"
    )

    # Renumber kept footnotes sequentially
    old_to_new = {}
    for idx, fn in enumerate(kept_footnotes, start=1):
        old_key = fn.get("key")
        old_to_new[old_key] = idx
        fn["key"] = idx

    block_data["footnotes"] = kept_footnotes

    # Update inline markers in translated content
    translated_content = block_data.get("translated_content", "")
    if translated_content:
        block_data["translated_content"] = _remap_markers(
            translated_content, old_to_new, removed_keys
        )

    return block_data


def validate_and_trim_all_blocks(
    data: Dict[str, Any],
    max_footnotes: Optional[int] = None,
    limits: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """
    Validate and trim footnote density across all blocks in a work.

    Args:
        data: Full work JSON data with structure.body.chapters
        max_footnotes: Override max footnotes per block
        limits: Custom limits dict

    Returns:
        Summary dict with total_blocks, trimmed_blocks, total_removed
    """
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
    total_blocks = 0
    trimmed_blocks = 0
    total_removed = 0

    for chapter in chapters:
        for block in chapter.get("content_blocks", []):
            total_blocks += 1
            result = validate_density(block, max_footnotes, limits)
            if not result["passed"]:
                before = result["footnote_count"]
                trim_excess_footnotes(block, max_footnotes, limits)
                removed = before - len(block.get("footnotes", []))
                total_removed += removed
                trimmed_blocks += 1

    summary = {
        "total_blocks": total_blocks,
        "trimmed_blocks": trimmed_blocks,
        "total_removed": total_removed,
    }

    logger.info(
        f"Density validation complete: {trimmed_blocks}/{total_blocks} blocks trimmed, "
        f"{total_removed} footnotes removed"
    )

    return summary


def _remap_markers(
    text: str,
    old_to_new: Dict[int, int],
    removed_keys: set,
) -> str:
    """
    Remap inline footnote markers [N] based on old->new key mapping.
    Remove markers for deleted footnotes.

    Args:
        text: Text containing inline markers like [1], [2], etc.
        old_to_new: Mapping from old key -> new key for kept footnotes
        removed_keys: Set of old keys that were removed

    Returns:
        Text with remapped markers
    """

    def replace_marker(match):
        old_key = int(match.group(1))
        if old_key in removed_keys:
            return ""  # Strip marker for removed footnote
        new_key = old_to_new.get(old_key)
        if new_key is not None:
            return f"[{new_key}]"
        return match.group(0)  # Keep unchanged if not in mapping

    return re.sub(r"\[(\d+)\]", replace_marker, text)
