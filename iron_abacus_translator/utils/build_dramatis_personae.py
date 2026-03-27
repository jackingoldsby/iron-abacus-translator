#!/usr/bin/env python3
"""
Dramatis Personae Builder (Stage 6d)

Harvests character-name footnotes from translated content into a structured
Dramatis Personae list. Strips those footnotes from the body text, renumbers
remaining footnotes, and classifies entries via LLM (three-way: not_person /
historical / fictional).

Position in pipeline: after cleanup_6c, before qg_post_cleanup.

Usage (programmatic):
    from utils.build_dramatis_personae import build_dramatis_personae
    dp_entries = build_dramatis_personae(work_data, client=deepseek_client)
    # work_data is modified in place (character footnotes stripped, renumbered)
    # dp_entries stored in work_data["dramatis_personae"]
"""

import json
import logging
import re
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Candidate extraction — collect ALL footnotes, let the LLM classify
# ---------------------------------------------------------------------------

def _extract_all_footnote_candidates(
    chapters: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Collect all footnotes as DP candidates. The LLM will classify.

    Returns a list of candidate dicts with location info for later stripping.
    """
    candidates = []
    for ch_idx, chapter in enumerate(chapters):
        for blk_idx, block in enumerate(chapter.get("content_blocks", [])):
            for fn in block.get("footnotes", []):
                ideogram = fn.get("ideogram", "")
                explanation = fn.get("explanation", "")
                if ideogram and explanation:
                    candidates.append({
                        "ideogram": ideogram,
                        "pinyin": fn.get("pinyin", ""),
                        "explanation": explanation,
                        "ch_idx": ch_idx,
                        "blk_idx": blk_idx,
                        "key": fn.get("key", 0),
                    })
    return candidates


# ---------------------------------------------------------------------------
# Core: harvest + strip + renumber
# ---------------------------------------------------------------------------

def build_dramatis_personae(
    data: Dict[str, Any],
    client=None,
    validate_historical: bool = True,
) -> List[Dict[str, Any]]:
    """
    Harvest character-name footnotes into a Dramatis Personae list.

    LLM-first approach:
    1. Collect ALL footnotes as candidates
    2. Send to LLM for four-way classification
       (not_person / historical / fictional / group)
    3. historical + fictional + group entries become DP entries
    4. Dedup by ideogram similarity + LLM confirmation
    5. Strip DP footnotes from body, renumber remaining

    Args:
        data: Full work JSON (modified in place)
        client: LLM client for classification (required for useful results)
        validate_historical: Whether to run LLM classification pass

    Returns:
        List of dramatis personae entries
    """
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
    if not chapters:
        logger.warning("No chapters found in data")
        data["dramatis_personae"] = []
        return []

    # --- Pass 1: Collect ALL footnotes as candidates ---
    all_candidates = _extract_all_footnote_candidates(chapters)
    if not all_candidates:
        logger.info("No footnotes found to harvest")
        data["dramatis_personae"] = []
        return []

    # Deduplicate by ideogram: keep first occurrence of each
    seen_characters: Dict[str, Dict[str, Any]] = {}
    pinyin_variants: Dict[str, set] = {}

    for cand in all_candidates:
        ideogram = cand["ideogram"]
        pinyin = cand["pinyin"]

        if pinyin:
            pinyin_variants.setdefault(ideogram, set()).add(pinyin)

        if ideogram not in seen_characters:
            seen_characters[ideogram] = {
                "ideogram": ideogram,
                "pinyin": pinyin,
                "explanation": cand["explanation"],
                "first_chapter": cand["ch_idx"] + 1,
                "is_historical": False,  # LLM will set this
                "dp_type": "fictional",  # LLM will set this
            }

    logger.info(
        f"Collected {len(seen_characters)} unique footnote ideograms from "
        f"{len(all_candidates)} total footnotes"
    )

    # --- Pass 2a: LLM three-way classification ---
    if validate_historical and client and seen_characters:
        all_entries = list(seen_characters.values())
        logger.info(f"Classifying {len(all_entries)} entries via LLM...")
        rejected = _classify_entries(all_entries, client)
        if rejected:
            for ideogram in rejected:
                seen_characters.pop(ideogram, None)
            logger.info(
                f"LLM classified {len(rejected)} as not_person "
                f"(kept as body footnotes): {rejected}"
            )
    elif not client:
        logger.warning(
            "No LLM client provided — cannot classify entries. "
            "All footnotes will be treated as potential DP candidates."
        )

    if not seen_characters:
        logger.info("No character entries survived classification")
        data["dramatis_personae"] = []
        return []

    logger.info(
        f"{len(seen_characters)} entries survived classification "
        f"(historical + fictional + groups)"
    )

    # --- Pass 2b: Dedup by ideogram similarity + LLM confirmation ---
    if client and len(seen_characters) > 1:
        deduped = _dedup_similar_characters(seen_characters, client)
        if deduped:
            for ideogram in deduped:
                seen_characters.pop(ideogram, None)
            logger.info(f"Deduplicated {len(deduped)} alias entries: {deduped}")

    # Build character_fn_locations for surviving entries
    surviving_ideograms = set(seen_characters.keys())
    character_fn_locations: List[Tuple[int, int, int]] = []
    for ch_idx, chapter in enumerate(chapters):
        for blk_idx, block in enumerate(chapter.get("content_blocks", [])):
            for fn in block.get("footnotes", []):
                if fn.get("ideogram", "") in surviving_ideograms:
                    character_fn_locations.append(
                        (ch_idx, blk_idx, fn.get("key", 0))
                    )

    # --- Pass 3: Strip character footnotes from body ---
    stripped_count = _strip_character_footnotes(
        data, character_fn_locations
    )
    logger.info(f"Stripped {stripped_count} character footnotes from body")

    # --- Pass 4: Renumber remaining footnotes ---
    _renumber_remaining(data)

    # --- Pass 5: Normalize pinyin variants in body text ---
    normalized = _normalize_pinyin_variants(data, seen_characters, pinyin_variants)
    if normalized:
        logger.info(f"Normalized {normalized} pinyin variant(s) in body text")

    # --- Build final DP list ---
    _TYPE_ORDER = {"historical": 0, "fictional": 1, "group": 2}
    dp_list = sorted(
        seen_characters.values(),
        key=lambda e: (_TYPE_ORDER.get(e.get("dp_type", "fictional"), 1),
                       e["first_chapter"]),
    )

    data["dramatis_personae"] = dp_list
    n_hist = sum(1 for e in dp_list if e.get("dp_type") == "historical")
    n_fict = sum(1 for e in dp_list if e.get("dp_type") == "fictional")
    n_group = sum(1 for e in dp_list if e.get("dp_type") == "group")
    logger.info(
        f"Dramatis Personae: {len(dp_list)} entries "
        f"({n_hist} historical, {n_fict} fictional, {n_group} groups)"
    )

    return dp_list


def _normalize_pinyin_variants(
    data: Dict[str, Any],
    seen_characters: Dict[str, Dict[str, Any]],
    pinyin_variants: Dict[str, set],
) -> int:
    """Replace variant pinyin spellings with canonical form in body text.

    For each character in the DP, the first-occurrence pinyin is canonical.
    Any other pinyin variants found in footnotes for the same ideogram are
    treated as inconsistencies and replaced throughout the translated text.

    Example: 冒浣蓮 footnoted as both "Mào Huànlián" and "Mào Wǎnlián"
    → canonical is whichever appeared first; the other gets replaced everywhere.

    Returns:
        Number of distinct variant replacements applied.
    """
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
    replacements_applied = 0

    for ideogram, variants in pinyin_variants.items():
        if ideogram not in seen_characters:
            continue
        canonical = seen_characters[ideogram]["pinyin"]
        if not canonical:
            continue

        # Find non-canonical variants
        non_canonical = {v for v in variants if v != canonical}
        if not non_canonical:
            continue

        # For each variant, also build word-part replacements.
        # E.g., if canonical="Mào Huànlián" and variant="Mào Wǎnlián",
        # we want to replace "Wǎnlián" → "Huànlián" as well as the full form.
        # Split on spaces to find differing components.
        canonical_parts = canonical.split()

        for variant in non_canonical:
            variant_parts = variant.split()

            # Build replacement pairs: full form + differing individual parts
            replace_pairs = [(variant, canonical)]

            # If same number of parts, also replace differing sub-parts
            if len(variant_parts) == len(canonical_parts):
                for vp, cp in zip(variant_parts, canonical_parts):
                    if vp != cp:
                        replace_pairs.append((vp, cp))

            for old, new in replace_pairs:
                if old == new:
                    continue
                for chapter in chapters:
                    for block in chapter.get("content_blocks", []):
                        translated = block.get("translated_content", "")
                        if old in translated:
                            block["translated_content"] = translated.replace(
                                old, new
                            )

            replacements_applied += 1
            logger.info(
                f"  Normalized '{variant}' → '{canonical}' "
                f"for {ideogram}"
            )

    return replacements_applied


def _strip_character_footnotes(
    data: Dict[str, Any],
    locations: List[Tuple[int, int, int]],
) -> int:
    """Remove character footnotes from body blocks and clean up markers.

    Args:
        data: Work data (modified in place)
        locations: List of (chapter_idx, block_idx, footnote_key) to remove

    Returns:
        Number of footnotes removed
    """
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
    # Build lookup: (ch_idx, blk_idx) -> set of keys to remove
    removal_map: Dict[Tuple[int, int], set] = {}
    for ch_idx, blk_idx, fn_key in locations:
        removal_map.setdefault((ch_idx, blk_idx), set()).add(fn_key)

    removed = 0
    for (ch_idx, blk_idx), keys_to_remove in removal_map.items():
        if ch_idx >= len(chapters):
            continue
        blocks = chapters[ch_idx].get("content_blocks", [])
        if blk_idx >= len(blocks):
            continue

        block = blocks[blk_idx]
        footnotes = block.get("footnotes", [])
        translated = block.get("translated_content", "")

        # Remove markers from text
        for key in keys_to_remove:
            translated = re.sub(
                rf'\[{key}\]', '', translated
            )

        # Filter footnotes
        new_footnotes = [
            fn for fn in footnotes if fn.get("key") not in keys_to_remove
        ]

        removed += len(footnotes) - len(new_footnotes)
        block["footnotes"] = new_footnotes
        block["translated_content"] = translated.strip()

    return removed


def _renumber_remaining(data: Dict[str, Any]):
    """Renumber footnotes continuously per chapter after stripping.

    Updates both footnote keys and [N] markers in translated text.
    """
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

    for chapter in chapters:
        counter = 0
        for block in chapter.get("content_blocks", []):
            footnotes = block.get("footnotes", [])
            if not footnotes:
                continue

            translated = block.get("translated_content", "")
            old_to_new = {}

            new_footnotes = []
            for fn in footnotes:
                old_key = fn.get("key", 0)
                counter += 1
                old_to_new[old_key] = counter
                fn["key"] = counter
                new_footnotes.append(fn)

            # Update markers in text
            def _replace_marker(match):
                old_k = int(match.group(1))
                new_k = old_to_new.get(old_k)
                if new_k is not None:
                    return f"[{new_k}]"
                return ""  # orphaned marker

            translated = re.sub(r'\[(\d+)\]', _replace_marker, translated)
            block["translated_content"] = translated
            block["footnotes"] = new_footnotes

    # Clean up any remaining orphan markers
    for chapter in chapters:
        for block in chapter.get("content_blocks", []):
            fn_keys = {fn.get("key") for fn in block.get("footnotes", [])}
            translated = block.get("translated_content", "")
            if not translated:
                continue

            def _clean_orphan(match):
                k = int(match.group(1))
                return match.group(0) if k in fn_keys else ""

            block["translated_content"] = re.sub(
                r'\[(\d+)\]', _clean_orphan, translated
            )


# ---------------------------------------------------------------------------
# Dedup similar characters (ideogram substring matching + LLM confirmation)
# ---------------------------------------------------------------------------

def _dedup_similar_characters(
    seen_characters: Dict[str, Dict[str, Any]],
    client,
) -> List[str]:
    """Find and merge DP entries that refer to the same person.

    Uses the same approach as footnote dedup: find pairs with shared
    ideogram substrings (≥2 chars), then ask DeepSeek to confirm they're
    the same person. The entry with the richer explanation is kept.

    Returns list of ideograms to remove (the duplicates).
    """
    ideograms = list(seen_characters.keys())
    # Find candidate pairs by substring overlap
    candidates = []  # (primary, duplicate)
    checked = set()

    for i, a in enumerate(ideograms):
        if a in checked:
            continue
        for b in ideograms[i + 1:]:
            if b in checked:
                continue
            if len(a) < 2 or len(b) < 2:
                continue
            # Check if one contains the other (shared root ≥2 chars)
            if a in b or b in a:
                candidates.append((a, b))

    if not candidates:
        return []

    logger.info(f"Found {len(candidates)} candidate character pairs for dedup")

    # Ask LLM to confirm each pair
    rejected = []
    for a, b in candidates:
        entry_a = seen_characters.get(a)
        entry_b = seen_characters.get(b)
        if not entry_a or not entry_b:
            continue

        prompt = (
            f"Are these two Dramatis Personae entries the SAME person "
            f"(alternate names, titles, reign names, or aliases)?\n\n"
            f"Entry 1: {a} ({entry_a['pinyin']}): {entry_a['explanation'][:200]}\n"
            f"Entry 2: {b} ({entry_b['pinyin']}): {entry_b['explanation'][:200]}\n\n"
            f"Return ONLY a JSON object with this exact structure:\n"
            f'{{"same_person": true, "keep": "{a}"}}\n'
            f"or\n"
            f'{{"same_person": false, "keep": ""}}\n\n'
            f"If same_person is true, set \"keep\" to the ideogram of whichever entry "
            f"has the more recognizable or distinctive name (prefer personal names "
            f"over reign names or temple names)."
        )

        try:
            from utils.clients import LLMRequest
            response = client.chat(LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            ))

            text = response.text.strip()
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if not json_match:
                continue

            result = json.loads(json_match.group())
            if result.get("same_person"):
                keep = result.get("keep", a)
                remove = b if keep == a else a
                rejected.append(remove)
                logger.info(f"  Dedup: {remove} is alias of {keep}")
        except Exception as e:
            logger.warning(f"  Dedup LLM call failed for {a}/{b}: {e}")

    return rejected


# ---------------------------------------------------------------------------
# LLM character validation
# ---------------------------------------------------------------------------

_CLASSIFY_BATCH_SIZE = 50  # max entries per LLM call


def _classify_entries(
    entries: List[Dict[str, Any]],
    client,
) -> List[str]:
    """Four-way LLM classification: not_person / historical / fictional / group.

    - not_person: rejected (returned in reject list, kept as body footnotes)
    - historical: is_historical=True, dp_type="historical", dates prepended
    - fictional: dp_type="fictional"
    - group: dp_type="group" (sects, factions, gangs, organizations)

    Batches entries into chunks of _CLASSIFY_BATCH_SIZE to avoid
    overwhelming the LLM with huge prompts.

    Returns list of ideograms to reject (not_person only).
    """
    if not entries:
        return []

    all_rejected = []
    entry_map = {e["ideogram"]: e for e in entries}

    # Process in batches
    for batch_start in range(0, len(entries), _CLASSIFY_BATCH_SIZE):
        batch = entries[batch_start:batch_start + _CLASSIFY_BATCH_SIZE]
        batch_num = batch_start // _CLASSIFY_BATCH_SIZE + 1
        total_batches = (len(entries) + _CLASSIFY_BATCH_SIZE - 1) // _CLASSIFY_BATCH_SIZE

        if total_batches > 1:
            logger.info(
                f"  Classification batch {batch_num}/{total_batches} "
                f"({len(batch)} entries)"
            )

        rejected = _classify_batch(batch, entry_map, client)
        all_rejected.extend(rejected)

    return all_rejected


def _classify_batch(
    batch: List[Dict[str, Any]],
    entry_map: Dict[str, Dict[str, Any]],
    client,
) -> List[str]:
    """Classify a single batch of entries via LLM.

    Returns list of ideograms rejected as not_person.
    """
    names_block = "\n".join(
        f"- {e['ideogram']} ({e['pinyin']}): {e['explanation']}"
        for e in batch
    )

    prompt = f"""Classify each entry for a Dramatis Personae. Each entry is one of:

1. "not_person" — NOT an individual or group. Includes: proverbs, sayings, government titles/positions, places, objects, concepts, techniques, formations, historical events, idioms.
2. "historical" — A real person who existed in history. Provide birth-death dates if known.
3. "fictional" — A fictional character invented for the novel.
4. "group" — A named sect, faction, gang, clan, school, society, or organization that acts as a collective entity in the story. Both real and fictional groups qualify.

Return ONLY a JSON array. One object per entry. Exact structure:

[
  {{"ideogram": "魏忠賢", "classification": "historical", "dates": "1568–1627"}},
  {{"ideogram": "卓一航", "classification": "fictional", "dates": ""}},
  {{"ideogram": "武當派", "classification": "group", "dates": ""}},
  {{"ideogram": "龍門幫", "classification": "group", "dates": ""}},
  {{"ideogram": "錦衣衛", "classification": "group", "dates": ""}},
  {{"ideogram": "三年清知府，十萬雪花銀", "classification": "not_person", "dates": ""}}
]

Rules:
- "classification" must be exactly one of: "not_person", "historical", "fictional", "group"
- "dates" is birth–death for historical persons only (e.g. "1568–1627"), empty string otherwise
- "ideogram" must exactly match the input ideogram
- Sects (武當派, 嵩陽派), gangs (龍門幫), secret services (錦衣衛, 東廠), escort agencies → "group"
- Ethnic groups (滿洲, 蒙古人, 漢人), dynasties, titles (總督, 巡撫), places, proverbs, techniques, formations, events → "not_person"

Entries to classify:
{names_block}"""

    try:
        from utils.clients import LLMRequest
        response = client.chat(LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        ))

        text = response.text.strip()
        json_match = re.search(r'\[.*\]', text, re.DOTALL)
        if not json_match:
            logger.warning("Could not parse classification response for batch")
            return []

        results = json.loads(json_match.group())
        rejected = []

        for result in results:
            ideogram = result.get("ideogram", "")
            if ideogram not in entry_map:
                continue

            classification = result.get("classification", "fictional")

            if classification == "not_person":
                rejected.append(ideogram)
                logger.info(f"  Not a person: {ideogram}")
            elif classification == "historical":
                entry = entry_map[ideogram]
                entry["is_historical"] = True
                entry["dp_type"] = "historical"
                # Only prepend dates — don't append LLM-generated identity
                # to avoid hallucination/embellishment
                dates = result.get("dates", "")
                if dates and dates not in entry["explanation"]:
                    entry["explanation"] = f"({dates}) {entry['explanation']}"
                logger.info(f"  Historical: {ideogram}")
            elif classification == "group":
                entry = entry_map[ideogram]
                entry["dp_type"] = "group"
                logger.info(f"  Group: {ideogram}")
            else:
                entry_map[ideogram]["dp_type"] = "fictional"
                logger.info(f"  Fictional: {ideogram}")

        return rejected

    except Exception as e:
        logger.warning(f"Classification batch failed: {e}")
        return []
