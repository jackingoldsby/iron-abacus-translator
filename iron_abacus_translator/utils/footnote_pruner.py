#!/usr/bin/env python3
"""
Footnote Pruner — LLM-based quality enforcement for translated footnotes.

Sends batches of footnotes to DeepSeek for evaluation against ironclad
quality rules. Removes hallucinated content, trims plot commentary,
and strips cross-cultural tangents.

Runs as a pipeline stage after correction_apply, before epub_build.
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PRUNE_PROMPT = """You are a scholarly footnote editor for a translated Classical Chinese novel. Review each footnote and decide: REMOVE, TRIM, or KEEP.

═══ REMOVE entirely ═══

- Surname-only: "包 — A common Chinese surname" (reader doesn't need this)
- Fictional character descriptions: "A martial arts master known for his swordsmanship"
- Technique motion descriptions with no real martial lineage: "A kicking technique that hooks like a crutch"
- Fabricated historical claims you cannot verify: "A technique from the Hú Family Sabre Method dating to the Tang dynasty"
- Trivially obvious honorific patterns: "Master Hán, combining surname with respectful title yé"
- Too short (<20 chars) or just restates the English text
- References to ANY film, TV, modern media, video games

═══ TRIM (remove bad sentences, keep good core) ═══

- Cross-cultural tangents: remove sentences about India, Korea, Vietnam, Japan, Europe, Belgium, Sumer, etc.
- Plot commentary: remove "Here, X praises Y", "In this scene", "which explains why", "suggesting that the character"
- Self-referential: remove mentions of "the novel being translated", "popularized in the 1879 novel"
- Absurd tangents: remove Marvel Comics, Heinrich Böll, Tower of Babel, atmospheric physics, US Merchant Marine
- Wrong dynasty: remove Ming/Qing references in a Song dynasty story (or vice versa)
- Literary filler: remove "Such places often serve as", "It is worth noting", "This illustrates"
- Modern dates: remove references to post-1900 events
- Return ONLY the trimmed explanation text (the good part to keep)

═══ KEEP unchanged ═══

- Real geographic locations with province/region
- Historical institutions with dates/dynasty
- Acupoints with body location and martial significance
- Idioms/proverbs with their origin story
- Real martial schools (Tàijí, Shàolín, Wǔdāng, Xíngyì, Bāguà)
- Cultural practices explaining WHAT the practice IS
- Real historical persons with dates

═══ Response format ═══

Return valid JSON array. For each footnote:
{"idx": 0, "verdict": "KEEP"} or
{"idx": 0, "verdict": "REMOVE", "reason": "surname-only"} or
{"idx": 0, "verdict": "TRIM", "reason": "plot commentary", "trimmed": "the good explanation text to keep"}
"""


def prune_footnotes(
    data: Dict[str, Any],
    client=None,
    max_workers: int = 50,
    batch_size: int = 20,
) -> Dict[str, Any]:
    """Prune footnotes using DeepSeek LLM evaluation.

    Args:
        data: Full work JSON (modified in place).
        client: LLM client (DeepSeek). Created if None.
        max_workers: Parallel workers for batch calls.
        batch_size: Footnotes per LLM batch.

    Returns:
        Report dict with statistics.
    """
    if client is None:
        try:
            from utils.clients.llm_config import get_llm_client
            client = get_llm_client(provider="deepseek")
        except Exception as e:
            logger.warning(f"Could not init DeepSeek for pruning: {e}")
            return {"removed": 0, "trimmed": 0, "kept": 0, "error": str(e)}

    from utils.clients.llm_client import LLMRequest

    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

    # Collect all footnotes with location info
    all_fns = []  # (ch_idx, block_idx, fn_idx, fn_dict)
    for ch_idx, ch in enumerate(chapters):
        for block in ch.get("content_blocks", []):
            for fn_idx, fn in enumerate(block.get("footnotes", [])):
                all_fns.append({
                    "ch_idx": ch_idx,
                    "block_id": block.get("id", ""),
                    "fn_idx": fn_idx,
                    "ideogram": fn.get("ideogram", ""),
                    "pinyin": fn.get("pinyin", ""),
                    "explanation": fn.get("explanation", ""),
                    "fn_ref": fn,  # direct reference for mutation
                    "block_ref": block,
                })

    if not all_fns:
        return {"removed": 0, "trimmed": 0, "kept": len(all_fns)}

    logger.info(f"  Footnote pruner: {len(all_fns)} footnotes → DeepSeek "
                f"({batch_size}/batch, {max_workers} workers)")

    # Process each footnote individually in parallel
    decisions = {}  # global_idx → verdict dict

    def _evaluate_one(global_idx, fn_info):
        user_msg = (
            f"Ideogram: {fn_info['ideogram']}\n"
            f"Pinyin: {fn_info['pinyin']}\n"
            f"Explanation: {fn_info['explanation']}\n\n"
            f"Verdict?"
        )

        try:
            response = client.chat(LLMRequest(
                messages=[
                    {"role": "system", "content": PRUNE_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                model="deepseek-chat",
                temperature=0.1,
                json_mode=True,
                timeout=30,
            ))

            result = response.parsed
            if isinstance(result, list) and result:
                result = result[0]
            if isinstance(result, dict):
                return global_idx, result
        except Exception as e:
            logger.debug(f"Prune failed for {fn_info['ideogram']}: {e}")
        return global_idx, {"verdict": "KEEP"}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_evaluate_one, i, fn): i
            for i, fn in enumerate(all_fns)
        }
        for fut in as_completed(futures):
            idx, decision = fut.result()
            decisions[idx] = decision

    # Apply decisions
    removed = 0
    trimmed = 0
    kept = 0
    details = []

    for global_idx, fn_info in enumerate(all_fns):
        decision = decisions.get(global_idx, {"verdict": "KEEP"})
        verdict = decision.get("verdict", "KEEP").upper()

        if verdict == "REMOVE":
            # Remove footnote and marker from text
            fn = fn_info["fn_ref"]
            block = fn_info["block_ref"]
            txt = block.get("translated_content", "")
            block["translated_content"] = txt.replace(f"[{fn['key']}]", "")
            block["footnotes"] = [
                f for f in block.get("footnotes", []) if f is not fn
            ]
            removed += 1
            details.append({
                "action": "REMOVE",
                "ch": fn_info["ch_idx"] + 1,
                "ideogram": fn_info["ideogram"],
                "reason": decision.get("reason", ""),
            })

        elif verdict == "TRIM":
            fn = fn_info["fn_ref"]
            new_text = decision.get("trimmed", "")
            if new_text and len(new_text) >= 20:
                fn["explanation"] = new_text
            trimmed += 1
            details.append({
                "action": "TRIM",
                "ch": fn_info["ch_idx"] + 1,
                "ideogram": fn_info["ideogram"],
                "reason": decision.get("reason", ""),
            })

        else:
            kept += 1

    # Renumber by text position
    _renumber_by_position(data)

    logger.info(f"  Footnote pruner: {removed} removed, {trimmed} trimmed, {kept} kept")

    return {
        "removed": removed,
        "trimmed": trimmed,
        "kept": kept,
        "total": len(all_fns),
        "details": details,
    }


def _renumber_by_position(data: Dict[str, Any]):
    """Renumber all footnotes chapter-continuously by text position."""
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

    for ch in chapters:
        fn_counter = 0
        for block in ch.get("content_blocks", []):
            translated = block.get("translated_content", "")
            footnotes = block.get("footnotes", [])
            if not translated or not footnotes:
                continue

            # Sort by position
            present = []
            for fn in footnotes:
                pos = translated.find(f"[{fn['key']}]")
                if pos >= 0:
                    present.append((pos, fn))
            present.sort(key=lambda x: x[0])

            # Renumber
            old_to_new = {}
            for _pos, fn in present:
                fn_counter += 1
                old_to_new[fn["key"]] = fn_counter
                fn["key"] = fn_counter

            if old_to_new:
                for old_key, new_key in sorted(old_to_new.items(), reverse=True):
                    translated = translated.replace(
                        f"[{old_key}]", f"[__FN{new_key}__]"
                    )
                for new_key in old_to_new.values():
                    translated = translated.replace(
                        f"[__FN{new_key}__]", f"[{new_key}]"
                    )
                block["translated_content"] = translated

            block["footnotes"] = [fn for _pos, fn in present]

        # Strip orphan markers
        for block in ch.get("content_blocks", []):
            txt = block.get("translated_content", "")
            if not txt:
                continue
            fn_keys = {fn["key"] for fn in block.get("footnotes", [])}
            for m in re.finditer(r"\[(\d+)\]", txt):
                if int(m.group(1)) not in fn_keys:
                    txt = txt.replace(m.group(), "")
            block["translated_content"] = re.sub(r"  +", " ", txt)
