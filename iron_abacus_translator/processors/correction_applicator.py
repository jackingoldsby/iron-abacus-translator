#!/usr/bin/env python3
"""
Correction Applicator — Applies focused corrections to tagged blocks.

Reads _correction_tags from each block (set by CorrectionClassifier),
builds a focused correction prompt from only the relevant specialist rules,
and sends to DeepSeek for correction. Blocks tagged 'clean' are skipped.

Usage:
    from processors.correction_applicator import CorrectionApplicator

    applicator = CorrectionApplicator()
    data = applicator.correct_work(data)
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> Optional[dict]:
    """Extract JSON from response text."""
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON in markdown code block
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        # Try to find any JSON object
        match = re.search(r'\{[^{}]*"corrected_text"[^{}]*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


class CorrectionApplicator:
    """Applies focused corrections to tagged blocks using DeepSeek."""

    def __init__(self, model: str = "deepseek-chat", provider: str = "deepseek",
                 temperature: float = 0.2, max_workers: int = 50):
        self.model = model
        self.provider = provider
        self.temperature = temperature
        self.max_workers = max_workers
        self._client = None

    def _get_client(self):
        if self._client is None:
            from utils.clients.llm_config import get_llm_client
            self._client = get_llm_client(
                component="correction_apply",
                provider=self.provider,
                model=self.model,
            )
        return self._client

    def correct_work(self, data: dict,
                     prior_seen_ideograms: Optional[set] = None,
                     prior_seen_pinyin: Optional[set] = None) -> dict:
        """Correct all tagged blocks in the work.

        Reads _correction_tags from each block. Skips blocks tagged 'clean'.
        Modifies translated_content and footnotes in place.
        Returns the modified data dict.
        """
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

        # Tags handled by programmatic cleanup — don't need LLM correction
        PROGRAMMATIC_ONLY_TAGS = {"double_space", "empty_footnote", "orphan_marker"}

        # Collect blocks that need correction
        tasks = []
        skipped = 0
        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                tags = block.get("_correction_tags", [])
                if not tags or tags == ["clean"]:
                    skipped += 1
                    continue
                if not block.get("translated_content"):
                    continue
                # Skip blocks whose ONLY tags are programmatic-only
                llm_tags = [t for t in tags if t not in PROGRAMMATIC_ONLY_TAGS]
                if not llm_tags:
                    skipped += 1
                    continue
                tasks.append(block)

        if not tasks:
            logger.info(f"No blocks need correction ({skipped} clean)")
            return data

        logger.info(f"Correcting {len(tasks)} blocks ({skipped} clean skipped, "
                     f"max_workers={self.max_workers})")

        corrected_count = 0
        unchanged_count = 0
        error_count = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for block in tasks:
                fut = executor.submit(self._correct_one, block)
                futures[fut] = block

            for fut in as_completed(futures):
                block = futures[fut]
                block_id = block.get("id", "unknown")
                try:
                    result = fut.result()
                    if result is None:
                        unchanged_count += 1
                        continue

                    corrected_text, corrected_footnotes, changes = result

                    if not changes:
                        unchanged_count += 1
                        continue

                    # Normalize: convert any <sup>N</sup> to [N] markers
                    import re as _re
                    corrected_text = _re.sub(
                        r'<sup>(\d+)</sup>', r'[\1]', corrected_text
                    )

                    # Guard: reject corrections that truncate content
                    original_text = block.get("translated_content", "")
                    if len(corrected_text) < len(original_text) * 0.8:
                        logger.warning(
                            f"  {block_id}: correction rejected — output "
                            f"({len(corrected_text)} chars) is <80% of original "
                            f"({len(original_text)} chars), likely truncated"
                        )
                        unchanged_count += 1
                        continue

                    # Apply corrected text
                    block["translated_content"] = corrected_text

                    # Merge footnotes: preserve original explanations, accept removes only
                    # Guard: correction must NOT add new footnotes — cleanup already
                    # decided what to keep. Only accept reductions or unchanged.
                    if corrected_footnotes is not None:
                        original_fns = block.get("footnotes", [])
                        merged = self._merge_footnotes(original_fns, corrected_footnotes)
                        if len(merged) <= len(original_fns):
                            block["footnotes"] = merged
                        else:
                            logger.warning(
                                f"  {block_id}: correction tried to ADD footnotes "
                                f"({len(original_fns)} → {len(merged)}) — rejected"
                            )

                    corrected_count += 1

                    logger.debug(f"  {block_id}: {', '.join(changes)}")

                except Exception as e:
                    logger.error(f"Correction failed for {block_id}: {e}")
                    error_count += 1

        logger.info(
            f"Correction complete: {corrected_count} corrected, "
            f"{unchanged_count} unchanged, {error_count} errors"
        )

        # Clean up temporary tags
        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                block.pop("_correction_tags", None)
                block.pop("_cleanup_removed_ideograms", None)
                block.pop("_gender_review_needed", None)

        # Relocate misplaced footnotes to correct blocks
        # (Safe now — footnote merge guard prevents explanation corruption)
        data = self._relocate_footnotes(data)

        # Dedup footnotes: keep only first occurrence of each ideogram across the work
        data = self._dedup_footnotes(data,
                                     prior_seen_ideograms=prior_seen_ideograms,
                                     prior_seen_pinyin=prior_seen_pinyin)

        # LLM sweep: remove fictional/meta/trivial footnotes
        data = self._strip_bad_footnotes(data)

        # NOTE: _verify_marker_placement disabled — the LLM moves markers
        # to wrong positions more often than it fixes them (e.g., kàng marker
        # moved to "divided three ways"). cleanup_6c already has its own
        # marker verification pass which is more conservative.

        # Single programmatic pass: fix punctuation, reorder, strip orphans
        data = self._finalize_footnotes(data)

        # Final programmatic cleanup: double spaces, empty footnotes
        data = self._programmatic_cleanup(data)

        return data

    def _relocate_footnotes(self, data: dict, search_radius: int = 5) -> dict:
        """Relocate footnotes whose ideogram doesn't appear in their block's source text.

        1. Programmatic: find the first block containing the ideogram in source
        2. LLM: place the marker at the correct position in the target block's English
        """
        import re

        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        relocated = 0

        for chapter in chapters:
            blocks = chapter.get("content_blocks", [])
            block_sources = [
                block.get("content", "") or block.get("source_content", "")
                for block in blocks
            ]

            moves = []  # (from_block_idx, fn, to_block_idx)

            for block_idx, block in enumerate(blocks):
                footnotes = block.get("footnotes", [])
                if not footnotes:
                    continue

                source = block_sources[block_idx]
                staying = []
                for fn in footnotes:
                    ideogram = fn.get("ideogram", "")
                    if not ideogram or ideogram in source:
                        staying.append(fn)
                        continue

                    # Search for the FIRST block containing this ideogram
                    found_idx = None
                    # Search forward first (most likely), then backward
                    for candidate_idx in range(len(blocks)):
                        if ideogram in block_sources[candidate_idx]:
                            found_idx = candidate_idx
                            break

                    if found_idx is not None and found_idx != block_idx:
                        moves.append((block_idx, fn, found_idx))
                    else:
                        staying.append(fn)

                if len(staying) != len(footnotes):
                    block["footnotes"] = staying
                    for i, fn in enumerate(staying, 1):
                        fn["key"] = i
                    text = block.get("translated_content", "")
                    if not staying:
                        text = re.sub(r'\[\d+\]', '', text)
                    else:
                        marker_idx = 0
                        def _renum_stay(m):
                            nonlocal marker_idx
                            marker_idx += 1
                            if marker_idx <= len(staying):
                                return f"[{marker_idx}]"
                            return ""
                        text = re.sub(r'\[\d+\]', _renum_stay, text)
                    block["translated_content"] = re.sub(r'  +', ' ', text)

            # Apply moves — use LLM to place markers correctly
            if moves:
                relocated += self._apply_footnote_moves(moves, blocks)

        if relocated:
            logger.info(f"  Footnote relocation: {relocated} moved to correct blocks")

        return data

    def _apply_footnote_moves(self, moves: list, blocks: list) -> int:
        """Apply footnote moves, using LLM to place markers in target blocks."""
        from utils.clients.llm_client import LLMRequest

        applied = 0
        for from_idx, fn, to_idx in moves:
            target_block = blocks[to_idx]
            target_fns = target_block.get("footnotes", [])
            new_key = len(target_fns) + 1
            fn["key"] = new_key
            target_fns.append(fn)
            target_block["footnotes"] = target_fns

            # Use LLM to find where to place the marker
            text = target_block.get("translated_content", "")
            if not text:
                continue

            try:
                client = self._get_client()
                response = client.chat(LLMRequest(
                    messages=[
                        {"role": "system", "content": (
                            "You place footnote markers in English translations. "
                            "Given a footnote's ideogram and explanation, and the English text, "
                            "return the text with the marker [N] placed immediately after the "
                            "English word/phrase that corresponds to the footnoted Chinese term. "
                            "Place marker BEFORE any punctuation. "
                            "Return ONLY the modified text, nothing else."
                        )},
                        {"role": "user", "content": (
                            f"Place marker [{new_key}] in this text for footnote:\n"
                            f"Ideogram: {fn.get('ideogram', '')}\n"
                            f"Pinyin: {fn.get('pinyin', '')}\n"
                            f"Explanation: {fn.get('explanation', '')[:100]}\n\n"
                            f"Text:\n{text}"
                        )},
                    ],
                    model=self.model,
                    temperature=0.0,
                    max_tokens=len(text) + 100,
                    timeout=30,
                ))

                result_text = response.text.strip()
                # Verify the marker was actually placed
                if f"[{new_key}]" in result_text:
                    target_block["translated_content"] = result_text
                    applied += 1
                else:
                    # Fallback: place at end
                    target_block["translated_content"] = text.rstrip() + f"[{new_key}]"
                    applied += 1

            except Exception as e:
                logger.debug(f"  Marker placement LLM failed: {e}, using fallback")
                target_block["translated_content"] = text.rstrip() + f"[{new_key}]"
                applied += 1

        return applied

    @staticmethod
    def _dedup_footnotes(data: dict,
                         prior_seen_ideograms: Optional[set] = None,
                         prior_seen_pinyin: Optional[set] = None) -> dict:
        """Remove duplicate footnotes across the work — keep first occurrence only.

        When the correction stage adds footnotes (e.g. *chǐ* footnotes on
        multiple blocks), only the first occurrence should have the footnote.
        Subsequent occurrences keep the marker text but lose the footnote entry.

        Args:
            data: Full work JSON
            prior_seen_ideograms: Ideograms from prior volumes (cross-volume dedup)
            prior_seen_pinyin: Pinyin from prior volumes (cross-volume dedup)
        """
        # Load suppress list — any footnote on a suppressed term gets stripped
        try:
            from processors.translation_prompts import get_suppress_ideograms
            suppressed = get_suppress_ideograms()
        except Exception:
            suppressed = set()

        seen_ideograms = set(prior_seen_ideograms) if prior_seen_ideograms else set()
        seen_pinyin = set(prior_seen_pinyin) if prior_seen_pinyin else set()
        removed = 0

        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                footnotes = block.get("footnotes", [])
                if not footnotes:
                    continue

                surviving = []
                for fn in footnotes:
                    ideogram = fn.get("ideogram", "")
                    pinyin = fn.get("pinyin", "").lower().strip()
                    if not ideogram and not pinyin:
                        surviving.append(fn)
                        continue

                    # Check suppress list first
                    is_dupe = False
                    if ideogram and ideogram in suppressed:
                        is_dupe = True

                    # Check by ideogram: exact match or containment
                    if not is_dupe and ideogram:
                        is_dupe = ideogram in seen_ideograms
                        if not is_dupe:
                            for seen in seen_ideograms:
                                if seen in ideogram or ideogram in seen:
                                    is_dupe = True
                                    break

                    # Also check by pinyin (catches variant characters and pinyin-as-ideogram)
                    if not is_dupe and pinyin and pinyin in seen_pinyin:
                        is_dupe = True

                    if is_dupe:
                        removed += 1
                        continue

                    if ideogram:
                        seen_ideograms.add(ideogram)
                    if pinyin:
                        seen_pinyin.add(pinyin)
                    surviving.append(fn)

                if len(surviving) != len(footnotes):
                    block["footnotes"] = surviving
                    import re
                    text = block.get("translated_content", "")

                    if not surviving:
                        # All footnotes removed — strip ALL markers
                        text = re.sub(r'\[\d+\]', '', text)
                    else:
                        # Renumber keys
                        for i, fn in enumerate(surviving, 1):
                            fn["key"] = i
                        # Re-index markers: keep first N (matching surviving count), strip rest
                        marker_idx = 0
                        def _replace_marker(m):
                            nonlocal marker_idx
                            marker_idx += 1
                            if marker_idx <= len(surviving):
                                return f"[{marker_idx}]"
                            return ""  # orphaned marker
                        text = re.sub(r'\[\d+\]', _replace_marker, text)

                    # Clean up double spaces left by removed markers
                    text = re.sub(r'  +', ' ', text)
                    block["translated_content"] = text

        if removed:
            logger.info(f"  Footnote dedup: removed {removed} duplicate footnotes, "
                        f"{len(seen_ideograms)} unique ideograms retained")

        return data

    def _strip_bad_footnotes(self, data: dict) -> dict:
        """LLM-based sweep: review each surviving footnote for quality.

        Each footnote evaluated independently in parallel (one request per
        footnote, 50 workers). Removes fictional descriptions, meta-commentary,
        trivial/inane explanations, and redundant content.
        """
        import re

        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

        # Collect all footnotes with their locations
        all_footnotes = []
        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                bid = block.get("id", "")
                trans = block.get("translated_content", "")
                for fn in block.get("footnotes", []):
                    all_footnotes.append({
                        "block_id": bid,
                        "key": fn.get("key"),
                        "ideogram": fn.get("ideogram", ""),
                        "explanation": fn.get("explanation", ""),
                        "block_text": trans[:200] if trans else "",
                    })

        if not all_footnotes:
            return data

        logger.info(f"  Bad footnote sweep: evaluating {len(all_footnotes)} footnotes "
                     f"(max_workers={self.max_workers})")

        to_remove = set()

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for fn_info in all_footnotes:
                fut = executor.submit(self._evaluate_footnote, fn_info)
                futures[fut] = fn_info

            for fut in as_completed(futures):
                fn_info = futures[fut]
                try:
                    result = fut.result()
                    action = result.get("action", "keep")
                    if action == "remove":
                        to_remove.add((fn_info["block_id"], fn_info["key"]))
                    # TRIM disabled — LLM hallucinates new content instead of trimming.
                    # Only KEEP or REMOVE. Footnote explanations are never modified
                    # after generation.
                except Exception as e:
                    logger.debug(f"  Footnote eval failed for {fn_info['block_id']}: {e}")

        if not to_remove:
            logger.info("  Bad footnote sweep: all footnotes clean")
            return data

        # Apply removals
        removed = 0
        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                bid = block.get("id", "")
                footnotes = block.get("footnotes", [])
                if not footnotes:
                    continue

                surviving = [fn for fn in footnotes if (bid, fn.get("key")) not in to_remove]
                if len(surviving) != len(footnotes):
                    removed += len(footnotes) - len(surviving)
                    block["footnotes"] = surviving
                    for i, fn in enumerate(surviving, 1):
                        fn["key"] = i
                    text = block.get("translated_content", "")
                    if not surviving:
                        text = re.sub(r'\[\d+\]', '', text)
                    else:
                        marker_idx = 0
                        def _renum(m):
                            nonlocal marker_idx
                            marker_idx += 1
                            if marker_idx <= len(surviving):
                                return f"[{marker_idx}]"
                            return ""
                        text = re.sub(r'\[\d+\]', _renum, text)
                    block["translated_content"] = re.sub(r'  +', ' ', text)

        logger.info(f"  Bad footnote sweep: {removed} removed")
        return data

    _FOOTNOTE_EVAL_PROMPT = """You are a footnote quality editor. Given a footnote's ideogram and explanation, plus a snippet of the surrounding English text, decide: KEEP, TRIM, or REMOVE.

**REMOVE** entirely if the footnote:
- Describes something as "fictional," "a fictional sect," "in this novel"
- Is ONLY a trivial restatement ("a Chinese term for...," "a form of address")
- Explains a self-explanatory epithet (Golden-Faced Buddha, Flying Fox) with no added cultural knowledge
- Is completely redundant with the surrounding text

**TRIM** if the footnote has valid content mixed with junk. You must ONLY DELETE phrases from the existing text — never add new content, never rewrite, never paraphrase. Strip:
- Meta-commentary about translation conventions ("rendered in pinyin," "honorifics are rendered...")
- Narrative commentary ("illustrates," "underscores the gravity," "signifies narratively")
- Redundant restatement of what the English already says
- Filler phrases ("in the context of wuxia fiction," "a common term in Chinese literature")
The trimmed version must be a SUBSET of the original text — every word in your output must appear in the original. You are deleting junk, not rewriting.

**KEEP** as-is if the footnote:
- Provides genuine historical context with dates and significance
- Explains a cultural concept concisely without filler
- Is already clean and focused

Return ONLY valid JSON:
- Keep: {"action": "keep"}
- Trim: {"action": "trim", "trimmed": "the cleaned-up explanation text"}
- Remove: {"action": "remove"}"""

    def _evaluate_footnote(self, fn_info: dict) -> dict:
        """Evaluate one footnote. Returns {"action": "keep|trim|remove", "trimmed": "..."}."""
        from utils.clients.llm_client import LLMRequest

        user_msg = (
            f"Ideogram: {fn_info['ideogram']}\n"
            f"Explanation: {fn_info['explanation']}\n"
            f"Surrounding text: {fn_info['block_text']}"
        )

        client = self._get_client()
        response = client.chat(LLMRequest(
            messages=[
                {"role": "system", "content": self._FOOTNOTE_EVAL_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            model=self.model,
            temperature=0.1,
            max_tokens=256,
            json_mode=True,
            timeout=30,
        ))

        parsed = response.parsed
        if parsed is None:
            parsed = _extract_json(response.text)

        if not parsed:
            return {"action": "keep"}

        return {
            "action": parsed.get("action", "keep"),
            "trimmed": parsed.get("trimmed", ""),
        }

    def _verify_marker_placement(self, data: dict) -> dict:
        """Verify every footnote marker is on the word matching its ideogram.

        For each block with footnotes, sends the translated text + footnote
        list to the LLM and asks it to return the text with all markers
        correctly positioned. Parallel, one block per request.
        """
        import re
        from utils.clients.llm_client import LLMRequest

        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

        # Collect blocks that have footnotes
        tasks = []
        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                if block.get("footnotes"):
                    tasks.append(block)

        if not tasks:
            return data

        logger.info(f"  Marker placement verification: {len(tasks)} blocks "
                     f"(max_workers={self.max_workers})")

        fixed = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for block in tasks:
                fut = executor.submit(self._verify_one_block_markers, block)
                futures[fut] = block

            for fut in as_completed(futures):
                block = futures[fut]
                try:
                    new_text = fut.result()
                    if new_text and new_text != block.get("translated_content", ""):
                        orig_text = block.get("translated_content", "")
                        # Guard: reject if LLM truncated content
                        if len(new_text) < len(orig_text) * 0.8:
                            logger.warning(
                                f"  Marker verify {block.get('id')}: rejected — "
                                f"output ({len(new_text)}) is <80% of original "
                                f"({len(orig_text)}), likely truncated"
                            )
                            continue
                        # Verify no duplicate markers were introduced
                        new_marker_nums = re.findall(r'\[(\d+)\]', new_text)
                        if len(new_marker_nums) == len(set(new_marker_nums)):
                            # No dupes — safe to apply
                            block["translated_content"] = new_text
                            fixed += 1
                        else:
                            logger.debug(f"  Duplicate markers in {block.get('id')}, skipping")
                except Exception as e:
                    logger.debug(f"  Marker verify failed for {block.get('id')}: {e}")

        if fixed:
            logger.info(f"  Marker placement: {fixed} blocks corrected")
        return data

    _MARKER_VERIFY_PROMPT = """You are a footnote marker placement specialist. You will receive an English translation with footnote markers [1], [2], etc., and the list of footnotes with their ideograms and pinyin.

Your job: verify each marker [N] is placed immediately after the English word/phrase that corresponds to footnote N's ideogram. If a marker is on the wrong word, MOVE it to the correct position.

Rules:
- Each marker goes immediately AFTER the English term that translates/corresponds to the footnote's ideogram
- Markers go BEFORE punctuation: "term[1]," not "term,[1]"
- Do NOT add or remove markers — only MOVE misplaced ones
- Do NOT change any words — only move the [N] markers
- If a footnote's ideogram is 大師 (Dàshī) and the marker is on *Zhàizhǔ*, move it to *Dàshī*
- CRITICAL: return the COMPLETE text with ALL sentences intact. Do NOT truncate, omit, or summarize any part. Every sentence from the input must appear in the output.

Return ONLY the corrected text, nothing else."""

    def _verify_one_block_markers(self, block: dict) -> Optional[str]:
        """Verify marker placement for one block. Returns corrected text or None."""
        from utils.clients.llm_client import LLMRequest

        text = block.get("translated_content", "")
        footnotes = block.get("footnotes", [])
        if not text or not footnotes:
            return None

        fn_list = "\n".join(
            f"[{fn.get('key')}] ideogram={fn.get('ideogram','')} "
            f"pinyin={fn.get('pinyin','')} — {fn.get('explanation','')[:60]}"
            for fn in footnotes
        )

        client = self._get_client()
        response = client.chat(LLMRequest(
            messages=[
                {"role": "system", "content": self._MARKER_VERIFY_PROMPT},
                {"role": "user", "content": f"Footnotes:\n{fn_list}\n\nText:\n{text}"},
            ],
            model=self.model,
            temperature=0.0,
            max_tokens=len(text) + 200,
            timeout=30,
        ))

        result = response.text.strip()
        # Strip any markdown code blocks the model might wrap it in
        if result.startswith("```"):
            lines = result.split("\n")
            result = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        return result if result else None

    @staticmethod
    def _finalize_footnotes(data: dict) -> dict:
        """Single pass: fix marker punctuation, reorder chapter-continuously, strip orphans.

        Combines three operations in one traversal:
        1. Move markers before punctuation: term.[N] → term[N].
        2. Renumber footnotes continuously per chapter: [1],[2],[3]...
        3. Strip orphaned markers (no matching footnote)
        """
        import re

        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        punct_fixed = 0
        renumbered = 0

        for chapter in chapters:
            chapter_fn_counter = 0
            for block in chapter.get("content_blocks", []):
                text = block.get("translated_content", "")
                if not text:
                    continue

                footnotes = block.get("footnotes", [])

                # Step 1: fix marker punctuation (before renumbering)
                new_text = re.sub(r'([.,;:!?])(\[\d+\])', r'\2\1', text)
                if new_text != text:
                    punct_fixed += 1
                    text = new_text

                if not footnotes:
                    # Strip stale markers
                    cleaned = re.sub(r'\[\d+\]', '', text)
                    if cleaned != text:
                        text = re.sub(r'  +', ' ', cleaned)
                        renumbered += 1
                    block["translated_content"] = text
                    continue

                # Step 1.5: deduplicate markers within the block
                # Keep only the LAST occurrence of each marker number
                # (for consolidated footnotes covering multiple terms,
                #  the marker belongs after the last term)
                marker_positions = {}  # marker_num -> list of (start, end) positions
                for m in re.finditer(r'\[\d+\]', text):
                    num = m.group()
                    marker_positions.setdefault(num, []).append((m.start(), m.end()))

                # Remove all but the last occurrence of each duplicate
                to_remove = set()
                for num, positions in marker_positions.items():
                    if len(positions) > 1:
                        # Keep last, remove all others
                        for start, end in positions[:-1]:
                            to_remove.add((start, end))

                if to_remove:
                    # Rebuild text, skipping removed positions
                    sorted_removes = sorted(to_remove)
                    new_parts = []
                    prev_end = 0
                    for start, end in sorted_removes:
                        new_parts.append(text[prev_end:start])
                        prev_end = end
                    new_parts.append(text[prev_end:])
                    text = "".join(new_parts)
                    text = re.sub(r'  +', ' ', text)

                # Step 2: renumber continuously across chapter
                key_map = {}
                for fn in footnotes:
                    old_key = fn.get("key", 0)
                    chapter_fn_counter += 1
                    key_map[old_key] = chapter_fn_counter
                    fn["key"] = chapter_fn_counter

                def _renumber(m):
                    old = int(m.group(1))
                    new = key_map.get(old)
                    if new is not None:
                        return f"[{new}]"
                    return ""  # orphaned marker

                new_text = re.sub(r'\[(\d+)\]', _renumber, text)
                if new_text != text:
                    renumbered += 1
                block["translated_content"] = re.sub(r'  +', ' ', new_text)

        if punct_fixed or renumbered:
            logger.info(f"  Finalize: {punct_fixed} punctuation fixes, {renumbered} blocks renumbered")

        return data

    @staticmethod
    def _programmatic_cleanup(data: dict) -> dict:
        """Final programmatic pass: fix double spaces, remove empty footnotes, fix orphan markers.

        These don't need an LLM — pure regex/data cleanup.
        """
        import re

        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        double_space_fixed = 0
        empty_fn_removed = 0
        orphan_fixed = 0

        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                text = block.get("translated_content", "")
                footnotes = block.get("footnotes", [])

                # 0. Verse line breaks: " / " → newline
                # Translators use " / " for caesura in verse couplets;
                # replace with actual line break for EPUB rendering
                if text and " / " in text:
                    text = text.replace(" / ", "\n")

                # 1. Double spaces
                if text and "  " in text:
                    new_text = re.sub(r'  +', ' ', text)
                    if new_text != text:
                        text = new_text
                        double_space_fixed += 1

                # 2. Empty footnotes (blank or <10 char explanation)
                if footnotes:
                    surviving = [
                        fn for fn in footnotes
                        if (fn.get("explanation") or "").strip()
                        and len((fn.get("explanation") or "").strip()) >= 10
                    ]
                    if len(surviving) < len(footnotes):
                        removed = len(footnotes) - len(surviving)
                        empty_fn_removed += removed
                        footnotes = surviving
                        block["footnotes"] = footnotes
                        # Renumber
                        for i, fn in enumerate(surviving, 1):
                            fn["key"] = i
                        if not surviving:
                            text = re.sub(r'\[\d+\]', '', text)
                        else:
                            marker_idx = 0
                            def _renum(m):
                                nonlocal marker_idx
                                marker_idx += 1
                                if marker_idx <= len(surviving):
                                    return f"[{marker_idx}]"
                                return ""
                            text = re.sub(r'\[\d+\]', _renum, text)
                        text = re.sub(r'  +', ' ', text)

                # 2b. Strip pop culture / anachronistic references from footnotes
                if footnotes:
                    _POP_CULTURE = re.compile(
                        r',?\s*(?:such as|similar to|like|akin to|comparable to|reminiscent of)'
                        r'[^.]*(?:Game of Thrones|Song of Ice and Fire|Lord of the Rings'
                        r'|Harry Potter|Star Wars|Marvel|Westeros|Hogwarts|anime|manga'
                        r'|Night.s Watch|Jedi|Avengers|Tolkien)[^.]*\.?',
                        re.IGNORECASE,
                    )
                    for fn in footnotes:
                        expl = fn.get("explanation", "")
                        if _POP_CULTURE.search(expl):
                            fn["explanation"] = _POP_CULTURE.sub(".", expl).strip()
                            fn["explanation"] = re.sub(r'\.\s*\.', '.', fn["explanation"])

                # 3. Orphan markers (marker with no footnote)
                if text:
                    marker_keys = set(int(m) for m in re.findall(r'\[(\d+)\]', text))
                    fn_keys = set(fn.get("key", 0) for fn in footnotes)
                    orphans = marker_keys - fn_keys
                    if orphans:
                        for orphan_key in orphans:
                            text = text.replace(f"[{orphan_key}]", "")
                        text = re.sub(r'  +', ' ', text)
                        orphan_fixed += len(orphans)

                block["translated_content"] = text

        if double_space_fixed or empty_fn_removed or orphan_fixed:
            logger.info(
                f"  Programmatic cleanup: {double_space_fixed} double-space fixes, "
                f"{empty_fn_removed} empty footnotes removed, "
                f"{orphan_fixed} orphan markers stripped"
            )

        return data

    @staticmethod
    def _merge_footnotes(originals: list, corrected: list) -> list:
        """Merge corrector output with original footnotes.

        Rules:
        - Existing footnotes: keep original ideogram + explanation (corrector can't rewrite)
        - Removed footnotes: if corrector dropped an ideogram, it stays dropped
        - New footnotes: if corrector added a new ideogram, accept it
        - Key numbering: from corrected output (corrector may have renumbered for marker placement)
        """
        # Build lookup of original explanations by ideogram
        orig_by_ideogram = {}
        for fn in originals:
            ig = fn.get("ideogram", "")
            if ig:
                orig_by_ideogram[ig] = fn

        merged = []
        for fn in corrected:
            ig = fn.get("ideogram", "")
            if ig in orig_by_ideogram:
                # Existing footnote — preserve original explanation, use corrected key
                orig = orig_by_ideogram[ig]
                merged.append({
                    "key": fn.get("key", orig.get("key")),
                    "ideogram": orig.get("ideogram", ""),
                    "pinyin": orig.get("pinyin", ""),
                    "explanation": orig.get("explanation", ""),
                })
            else:
                # New footnote from corrector — accept as-is
                merged.append(fn)

        return merged

    def _correct_one(self, block: dict) -> Optional[tuple]:
        """Correct a single block. Returns (corrected_text, corrected_footnotes, changes) or None."""
        from utils.clients.llm_client import LLMRequest
        from processors.correction_prompts import build_correction_prompt

        tags = block.get("_correction_tags", [])
        system_prompt = build_correction_prompt(tags)
        if not system_prompt:
            return None

        source = block.get("content", "") or block.get("source_content", "")
        translation = block.get("translated_content", "")
        footnotes = block.get("footnotes", [])

        # Build user message with source, translation, and footnotes
        parts = [
            f"**Issue categories flagged:** {', '.join(tags)}",
            f"\n**Source Chinese:**\n{source}",
            f"\n**Current English Translation:**\n{translation}",
        ]
        if footnotes:
            fn_lines = []
            for fn in footnotes:
                fn_lines.append(
                    f"[{fn.get('key', '?')}] {fn.get('ideogram', '')} "
                    f"({fn.get('pinyin', '')}) — {fn.get('explanation', '')}"
                )
            parts.append(f"\n**Current Footnotes:**\n" + "\n".join(fn_lines))
        else:
            parts.append("\n**Current Footnotes:** None")

        parts.append("\nCorrect ONLY the flagged issues. Return the full corrected block.")

        user_msg = "\n".join(parts)

        client = self._get_client()
        response = client.chat(LLMRequest(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            model=self.model,
            temperature=self.temperature,
            max_tokens=4096,
            json_mode=True,
            timeout=120,
        ))

        parsed = response.parsed
        if parsed is None:
            parsed = _extract_json(response.text)

        if not parsed:
            logger.debug(f"Unparseable correction for {block.get('id', '?')}")
            return None

        corrected_text = parsed.get("corrected_text", "")
        changes = parsed.get("changes_made", [])

        if not corrected_text:
            return None

        # Even if changes_made is empty, check if text actually differs
        original_text = block.get("translated_content", "")
        if corrected_text.strip() == original_text.strip() and not changes:
            return None

        # Parse corrected footnotes
        corrected_footnotes = None
        raw_fns = parsed.get("corrected_footnotes")
        if raw_fns is not None and isinstance(raw_fns, list):
            corrected_footnotes = []
            for fn in raw_fns:
                corrected_footnotes.append({
                    "key": fn.get("key", 0),
                    "ideogram": fn.get("ideogram", ""),
                    "pinyin": fn.get("pinyin", ""),
                    "explanation": fn.get("explanation", ""),
                })

        return corrected_text, corrected_footnotes, changes
