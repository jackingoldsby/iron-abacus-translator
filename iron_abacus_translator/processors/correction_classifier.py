#!/usr/bin/env python3
"""
Correction Classifier — Tags translated blocks with issue categories.

Uses gpt-4.1-nano for fast, cheap classification. Each block is independently
classified in parallel. Blocks tagged 'clean' skip the correction stage.

Usage:
    from processors.correction_classifier import CorrectionClassifier

    classifier = CorrectionClassifier()
    data = classifier.classify_work(data)
    # Each block now has block["_correction_tags"] = ["measurement", "register"] or ["clean"]
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

CLASSIFIER_SYSTEM_PROMPT = """You are a translation quality classifier for Classical Chinese literature translated into English. You will receive a block of Chinese source text, its English translation, and any footnotes. Your job is to TAG the block with issue categories — do NOT fix anything, just classify.

**Issue categories** (tag ALL that apply):

- `measurement` — Translation uses Western units (feet, inches, pounds, miles, yards) where the Chinese source has 斤/兩/里/丈/尺/寸/更/時辰. Also: Chinese measurement pinyin that is NOT italicized (should be wrapped in *asterisks*): li instead of *lǐ*, jin instead of *jīn*, chi instead of *chǐ*. Also: pinyin onomatopoeia/sound effects NOT italicized — e.g. "Sōu sōu sōu" should be "*Sōu sōu sōu*", "pēng" should be "*pēng*". Any pinyin (measurements, sound effects) without asterisks is a measurement issue.

- `weapon` — The English phrase "long sword" or "long swords" appears ANYWHERE in the translation (長劍 should be just "sword" — this is ALWAYS a weapon issue, no exceptions). Also: 寶劍 translated as "sword" when the weapon is actually a dagger or other type; 棒 as "cudgel" in a domestic scene (should be "poker"); 錐 as "spike" when thrown (should be "dart"). **If you see "long sword" in the English, tag `weapon` immediately.**

- `register` — Modern English inappropriate for wuxia period setting: "heist," "mark" (for target), "gang" (for 幫), "Messrs.," "a cut above," "mutually assured destruction," "top-notch," corporate/legal/military jargon. Also: European supernatural creatures ("goblins," "elves") substituted for Chinese 鬼/妖/精.

- `footnote_placement` — A footnote marker [N] appears on the wrong word (not the English term corresponding to the footnoted Chinese). Or inline glosses like sabre[dāo] appear instead of proper footnotes. Also: a footnote's ideogram/pinyin doesn't match the word the marker is attached to (e.g. marker on *Shīxiōng* but footnote explains 師妹 shīmèi — completely wrong term).

- `footnote_consolidation` — Two adjacent footnotes explain closely related or overlapping terms that should be one footnote (e.g. 吳[3]越[4] with near-identical explanations).

- `footnote_missing` — Missing footnotes for: acupoints (穴), major wuxia sects on first mention (少林/武當/崑崙/峨嵋), classical literary allusions, Thirty-Six Stratagems or Art of War references, 十八般武藝, character-count references ("seven characters") without Chinese breakdown, or legendary named weapons/artifacts (e.g. famous swords listed by name without footnotes explaining their meaning and significance). ALSO tag if: a footnote describes something as "fictional" or "a fictional sect/school"; or the text mentions a reign year (e.g. "forty-fifth year of the Qiánlóng reign") but no footnote gives the CE date conversion.

- `honorific` — English translations where italicized pinyin expected: "Senior Brother" (should be *Shīxiōng*), "Clan Leader" (should be *Bāngzhǔ*), "Village Master" (should be *Zhuāngzhǔ*), "Great Monk" (should be *Dàshī*), "Abbot" (should be *Fāngzhàng*), "Elder" when used as address (should be *Qiánbèi*), "Sect Leader" (should be *Zhǎngmén*). ANY martial/social honorific rendered as English instead of italicized pinyin is a `honorific` issue. Also: honorific pinyin that is NOT italicized — shīxiōng without asterisks (should be *Shīxiōng*), gūniáng without asterisks, dàshī without asterisks, etc. **If you see any honorific pinyin in the text without *asterisks* around it, tag `honorific`.** Also: translated surnames (熊 as "Bear," 馬 as "Horse").

- `idiom_curse` — Chinese curse/idiom translated literally producing dead English: "short-lived villain" (短命的), "his grandmother's bear" (他奶奶的熊), "mistake your vinegar" (喝錯了醋), "gall bladder quivered" (literal organ metaphor).

- `technique_name` — Martial technique name with comical/inaccurate verb: "Spits Its Whiskers" (should be "Lashes"), "Explores the Cave" (should be "Probes"). Also: combat direction reversed (blocking low described as "raising" sword). Also: a footnote on a technique name that merely restates the imagery without adding cultural knowledge — these are trivial and should be removed.

- `clean` — No issues detected. Use this ONLY if none of the above categories apply.

**Return ONLY valid JSON:**
{"tags": ["category1", "category2"]}

If no issues: {"tags": ["clean"]}

Be thorough but precise. Only tag categories where you see a clear instance."""


def _extract_json(text: str) -> Optional[dict]:
    """Extract JSON from response text."""
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{[^{}]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


class CorrectionClassifier:
    """Tags translated blocks with issue categories using nano."""

    def __init__(self, model: str = "deepseek-chat", provider: str = "deepseek",
                 temperature: float = 0.1, max_workers: int = 50):
        self.model = model
        self.provider = provider
        self.temperature = temperature
        self.max_workers = max_workers
        self._client = None

    def _get_client(self):
        if self._client is None:
            from utils.clients.llm_config import get_llm_client
            self._client = get_llm_client(
                component="correction_classify",
                provider=self.provider,
                model=self.model,
            )
        return self._client

    def classify_work(self, data: dict) -> dict:
        """Classify all translated blocks in the work.

        Modifies blocks in place, adding _correction_tags to each.
        Returns the modified data dict.
        """
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

        # Collect all translatable blocks
        tasks = []
        for ch_idx, chapter in enumerate(chapters):
            for block in chapter.get("content_blocks", []):
                if not block.get("translated_content"):
                    continue
                tasks.append(block)

        if not tasks:
            logger.info("No translated blocks to classify")
            return data

        logger.info(f"Classifying {len(tasks)} blocks (max_workers={self.max_workers})")

        clean_count = 0
        tagged_count = 0
        tag_counts: Dict[str, int] = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for block in tasks:
                fut = executor.submit(self._classify_one, block)
                futures[fut] = block

            for fut in as_completed(futures):
                block = futures[fut]
                try:
                    tags = fut.result()
                    block["_correction_tags"] = tags

                    if tags == ["clean"]:
                        clean_count += 1
                    else:
                        tagged_count += 1
                        for tag in tags:
                            tag_counts[tag] = tag_counts.get(tag, 0) + 1

                except Exception as e:
                    block_id = block.get("id", "unknown")
                    logger.error(f"Classification failed for {block_id}: {e}")
                    block["_correction_tags"] = ["clean"]  # Default to clean on error
                    clean_count += 1

        logger.info(
            f"Classification complete: {clean_count} clean, {tagged_count} tagged"
        )
        if tag_counts:
            sorted_tags = sorted(tag_counts.items(), key=lambda x: -x[1])
            tag_summary = ", ".join(f"{t}={c}" for t, c in sorted_tags)
            logger.info(f"  Tag distribution: {tag_summary}")

        return data

    def _classify_one(self, block: dict) -> List[str]:
        """Classify a single block. Returns list of tags."""
        from utils.clients.llm_client import LLMRequest

        source = block.get("content", "") or block.get("source_content", "")
        translation = block.get("translated_content", "")
        footnotes = block.get("footnotes", [])

        # Build user message
        parts = [
            f"**Source Chinese:**\n{source}",
            f"\n**English Translation:**\n{translation}",
        ]
        if footnotes:
            fn_lines = []
            for fn in footnotes:
                fn_lines.append(
                    f"[{fn.get('key', '?')}] {fn.get('ideogram', '')} "
                    f"({fn.get('pinyin', '')}) — {fn.get('explanation', '')}"
                )
            parts.append(f"\n**Footnotes:**\n" + "\n".join(fn_lines))

        user_msg = "\n".join(parts)

        client = self._get_client()
        response = client.chat(LLMRequest(
            messages=[
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            model=self.model,
            temperature=self.temperature,
            max_tokens=128,
            json_mode=True,
            timeout=30,
        ))

        parsed = response.parsed
        if parsed is None:
            parsed = _extract_json(response.text)

        if not parsed:
            logger.debug(f"Unparseable classification for {block.get('id', '?')}, defaulting to clean")
            return ["clean"]

        tags = parsed.get("tags", ["clean"])
        if not isinstance(tags, list) or not tags:
            return ["clean"]

        # Validate tags against known categories
        from processors.correction_prompts import CORRECTION_CATEGORIES
        valid_tags = [t for t in tags if t in CORRECTION_CATEGORIES or t == "clean"]

        return valid_tags if valid_tags else ["clean"]
