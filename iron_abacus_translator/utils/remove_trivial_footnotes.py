#!/usr/bin/env python3
"""
Trivial Footnote Removal Utility (Stage 6c)

AI-powered triviality scoring and removal of over-explanatory, obvious,
or plot-spoiling footnotes. Processes at work level (entire work at once)
following the same patterns as cleanup_character_footnotes.py (Stage 6a).

Usage:
    python utils/remove_trivial_footnotes.py --input file.json --output cleaned.json
    python utils/remove_trivial_footnotes.py --input file.json --dry-run

Programmatic:
    from utils.remove_trivial_footnotes import TrivialFootnoteRemover, TrivialityConfig
    remover = TrivialFootnoteRemover(TrivialityConfig())
    result = remover.process_file(input_path, output_path)
"""

import json
import logging
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from tqdm import tqdm

from utils.clients import get_llm_client, LLMRequest

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_openai_client():
    """Get LLM client from environment config."""
    return get_llm_client(component="cleanup")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TrivialityScore(BaseModel):
    """Triviality assessment for a single footnote."""
    footnote_key: int
    ideogram: str
    explanation: str
    triviality_score: int = Field(ge=0, le=100)
    cultural_specificity_score: int = Field(ge=0, le=100)
    should_remove: bool
    reasoning: str

    class Config:
        extra = "ignore"


class TrivialityConfig(BaseModel):
    """Configuration for triviality removal."""
    model: str = "gpt-4.1-nano"
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    batch_size: int = Field(default=10, gt=0)
    triviality_threshold: int = Field(default=50, ge=0, le=100)
    cultural_threshold: int = Field(default=50, ge=0, le=100)
    create_backup: bool = True
    max_retries: int = Field(default=3, ge=1)


class TrivialityResult(BaseModel):
    """Result of the triviality removal operation."""
    total_footnotes: int = 0
    analyzed_count: int = 0
    removed_count: int = 0
    duplicate_count: int = 0
    preserved_count: int = 0
    avg_triviality_removed: float = 0.0
    avg_cultural_preserved: float = 0.0
    scores: List[TrivialityScore] = Field(default_factory=list)
    removed_footnotes: List[Dict[str, Any]] = Field(default_factory=list)
    validation_passed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "summary": {
                "total_footnotes": self.total_footnotes,
                "analyzed_count": self.analyzed_count,
                "removed_count": self.removed_count,
                "duplicate_count": self.duplicate_count,
                "preserved_count": self.preserved_count,
                "removal_rate": (
                    f"{self.removed_count / self.total_footnotes * 100:.1f}%"
                    if self.total_footnotes > 0
                    else "0%"
                ),
                "avg_triviality_of_removed": round(self.avg_triviality_removed, 1),
                "avg_cultural_specificity_of_preserved": round(
                    self.avg_cultural_preserved, 1
                ),
                "validation_passed": self.validation_passed,
            },
            "removed_footnotes": self.removed_footnotes,
        }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_footnote_integrity(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate that inline markers and footnote arrays are consistent.

    Checks:
    - No orphaned markers (markers without matching footnotes)
    - Footnote keys are chapter-continuous (monotonically increasing across blocks)
    - No duplicate ideograms within the same block

    Args:
        data: Full work JSON data

    Returns:
        Dict with 'passed' (bool) and 'errors' (list of issues)
    """
    errors = []
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

    for ch_idx, chapter in enumerate(chapters):
        expected_next = 1  # chapter-continuous counter

        for block in chapter.get("content_blocks", []):
            block_id = block.get("id", "unknown")
            footnotes = block.get("footnotes", [])
            translated = block.get("translated_content", "")

            if not footnotes and not translated:
                continue

            # Extract markers from translated content
            markers = [int(m) for m in re.findall(r"\[(\d+)\]", translated)]
            unique_markers = sorted(set(markers))
            footnote_keys = [fn.get("key") for fn in footnotes]

            # Check for orphan markers (markers without matching footnotes)
            marker_set = set(unique_markers)
            key_set = set(footnote_keys)
            orphan_markers = marker_set - key_set
            if orphan_markers:
                errors.append(
                    f"{block_id}: orphan markers {sorted(orphan_markers)} "
                    f"have no matching footnotes"
                )

            # Check chapter-continuous numbering
            if footnotes:
                expected_keys = list(range(expected_next, expected_next + len(footnotes)))
                if footnote_keys != expected_keys:
                    errors.append(
                        f"{block_id}: footnote keys {footnote_keys} "
                        f"expected {expected_keys} (chapter-continuous)"
                    )
                expected_next += len(footnotes)

            # Check for duplicate ideograms within block
            ideograms = [fn.get("ideogram", "") for fn in footnotes]
            seen = set()
            for ideo in ideograms:
                if ideo in seen:
                    errors.append(
                        f"{block_id}: duplicate ideogram '{ideo}' within block"
                    )
                seen.add(ideo)

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "blocks_checked": sum(
            len(ch.get("content_blocks", []))
            for ch in chapters
        ),
    }


# ---------------------------------------------------------------------------
# Main processor
# ---------------------------------------------------------------------------

class TrivialFootnoteRemover:
    """Removes trivial and over-explanatory footnotes using AI scoring.

    Two-phase approach:
      Phase 1 (programmatic): Remove footnotes whose ideogram matches the
               suppress list — no API calls needed, instant.
      Phase 2 (API): Score remaining footnotes for triviality via OpenAI.
    """

    SYSTEM_PROMPT = """You are a ruthless editor reviewing footnotes in an English translation of Classical Chinese wuxia literature. Your job is to identify and REMOVE footnotes that do not add genuine cultural value.

**THE KEY QUESTION: Does this footnote teach the reader something about Chinese culture, history, or martial arts that they CANNOT infer from the English translation alone?**

If the answer is NO, the footnote should be REMOVED. Period.

**ALWAYS REMOVE these categories (triviality 80+, cultural 10 or less):**

1. **Pure translations** — the explanation just restates the English meaning:
   - "A fine steed" for 駿馬 → REMOVE (the English text already says "horse")
   - "Pine branches" for 松枝 → REMOVE
   - "Two persons" for 兩個 → REMOVE
   - "Pearls" for 珍珠 → REMOVE
   - "The sleeve of a garment" for 衣袖 → REMOVE
   - "Reaching out with the hand" for 伸手 → REMOVE
   - "Reined in his horse" for 勒住馬頭 → REMOVE
   - "A bottle's quantity" for 一瓶 → REMOVE
   ANY footnote that merely translates a common Chinese word/phrase into English is trivial.

2. **Fictional character names** — explanations of made-up characters:
   - "A personal name; a military officer leading the convoy" for 方慶 → REMOVE
   - "A character's name, possibly a kin or a disciple" for 澄兒 → REMOVE
   - "A character's name, likely a young woman" for 冒浣蓮 → REMOVE
   Fictional character names NEVER need footnotes. They are not real people.

3. **Emotions, actions, body language** — universally understood:
   - "Feeling somewhat warm" for 感到有些燠熱 → REMOVE
   - "Turning her face away to avoid embarrassment" for 把頭別過面 → REMOVE
   - "Feeling shy or embarrassed" for 覺不好意思 → REMOVE
   - "Constantly glancing back, indicating vigilance" for 回頭顧盼 → REMOVE

4. **Common objects/animals/nature** with no cultural dimension:
   - "Warhorse, the type of horse used in battle" for 馬 → REMOVE
   - "A sword with a long blade" for 長劍 → REMOVE
   - "Swallows, small migratory birds" for 群鶯 → REMOVE
   - "Clothing or attire indicating status" for 服飾上 → REMOVE

5. **Meta-narrative or obvious statements**:
   - "Next chapter to be unfolded" for 下回分解 → REMOVE
   - "Expressing genuine happiness" for 可慶呀 → REMOVE
   - "Betraying the imperial court" for 背叛朝廷 → REMOVE
   - "To flatter excessively" for 阿諛奉承 → REMOVE

6. **Spoilers or foreshadowing** (any cultural score):
   - "Who later betrays..." → REMOVE
   - "This leads to..." → REMOVE

**ONLY PRESERVE footnotes that provide GENUINE cultural enrichment:**

- Real historical figures with dates/context (Emperor Kāngxī, r. 1661-1722)
- Real historical events, eras, battles (Zhèngtǒng era, Battle of Tumu)
- Named martial arts techniques with explanation of their origin/style
- Buddhist/Taoist/Confucian concepts not obvious from English
- Real temples, mountains, passes with historical significance
- Traditional medicine, acupuncture, qi cultivation concepts
- Classical poetry forms, literary allusions to real works
- Cultural practices genuinely alien to Western readers (specific funeral rites, marriage customs)
- Real geographic/political context (dynasty details, regional significance)

**SCORING CALIBRATION:**

MUST REMOVE (triviality 80+, cultural < 15):
- "A fine steed" → triviality: 95, cultural: 0
- "Two persons" → triviality: 99, cultural: 0
- "Reaching out with the hand" → triviality: 95, cultural: 0
- "A personal name; a military officer" → triviality: 90, cultural: 5
- "Feeling shy or embarrassed" → triviality: 90, cultural: 5
- "The sleeve of a garment" → triviality: 95, cultural: 0
- "A sword with a long blade" → triviality: 90, cultural: 5
- "Next chapter to be unfolded" → triviality: 85, cultural: 10

MUST PRESERVE (triviality < 30, cultural 60+):
- "Emperor Kāngxī (r. 1661-1722), known for consolidating Qing rule" → triviality: 10, cultural: 90
- "Wǔtái Shān, one of the Four Sacred Buddhist Mountains of China" → triviality: 10, cultural: 85
- "Manjusri Bodhisattva, who symbolizes wisdom in Mahayana Buddhism" → triviality: 15, cultural: 90
- "Zhèngtǒng era (1436-1449), the reign of Emperor Yīngzōng before his capture" → triviality: 10, cultural: 95
- "Post roads (驛道): the imperial relay system connecting major cities" → triviality: 20, cultural: 75

BORDERLINE (use strict judgment — when in doubt, REMOVE):
- "Buddhist lanterns symbolize enlightenment" → triviality: 50, cultural: 45 → REMOVE (vague)
- "A phrase describing splendid temple architecture" → triviality: 70, cultural: 20 → REMOVE (just description)

**DEFAULT STANCE: REMOVE unless the footnote clearly passes the cultural enrichment test.**

For each footnote, return a JSON object with:
- footnote_index: (0-based index in the batch)
- should_remove: boolean
- triviality_score: 0-100 (higher = more trivial)
- cultural_specificity_score: 0-100 (higher = more culturally specific)
- reasoning: brief explanation

Return as: {"assessments": [...]}"""

    def __init__(self, config: TrivialityConfig):
        """Initialize the 4-phase trivial footnote remover.

        Args:
            config: TrivialityConfig controlling thresholds, batch size,
                    suppress-list path, and phase toggles.
        """
        self.config = config
        self.client = get_openai_client()
        self.result = TrivialityResult()
        # Ideograms whose first-occurrence footnote is protected from removal
        # because the term appears as italicized pinyin in the translated text
        self._protected_ideograms: set = set()

    def extract_footnotes_with_context(
        self, data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Extract all footnotes with their surrounding content context.

        Returns list of dicts with footnote info + content snippet for AI context.
        """
        footnotes = []
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

        for chapter_idx, chapter in enumerate(chapters):
            chapter_title = chapter.get("title", "Untitled")

            for block in chapter.get("content_blocks", []):
                block_id = block.get("id", "unknown")
                translated = block.get("translated_content", "")
                content_type = block.get("content_type", "narrative")

                # Truncate context to ~300 chars for prompt efficiency
                context_snippet = translated[:300] if translated else ""

                for fn in block.get("footnotes", []):
                    ideogram = fn.get("ideogram", "")
                    explanation = fn.get("explanation", "")
                    if not explanation:
                        continue

                    footnotes.append({
                        "ideogram": ideogram,
                        "explanation": explanation,
                        "pinyin": fn.get("pinyin", ""),
                        "key": fn.get("key"),
                        "block_id": block_id,
                        "chapter_title": chapter_title,
                        "content_type": content_type,
                        "context_snippet": context_snippet,
                    })

        return footnotes

    def _build_protected_set(self, data: Dict[str, Any]) -> set:
        """
        Identify ideograms that MUST keep their first-occurrence footnote.

        Scans translated text for italicized pinyin terms (*shīxiōng*, *qì*, etc.)
        and matches them to footnote ideograms via the footnote's pinyin field.
        These terms were deliberately kept untranslated by the translator, so the
        reader needs the footnote to understand what they mean.

        Returns a set of ideogram strings to protect.
        """
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

        # Collect all italicized pinyin terms from translated text
        italic_pinyins: set = set()
        italic_re = re.compile(r'\*([a-zA-Zàáèéìíòóùúǎǐǒǔāēīōūüǖǘǚǜ]+)\*')
        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                text = block.get("translated_content", "")
                if text:
                    for m in italic_re.finditer(text):
                        italic_pinyins.add(m.group(1).lower())

        if not italic_pinyins:
            return set()

        # Also add tone-stripped versions for matching
        italic_stripped = {_strip_tones(p) for p in italic_pinyins}

        # Match footnote pinyin to italicized terms — protect the ideogram
        protected = set()
        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                for fn in block.get("footnotes", []):
                    pinyin = fn.get("pinyin", "").strip()
                    if not pinyin:
                        continue
                    # Check each word in multi-word pinyin
                    words = pinyin.lower().split()
                    for w in words:
                        if w in italic_pinyins or _strip_tones(w) in italic_stripped:
                            protected.add(fn.get("ideogram", ""))
                            break

        logger.info(
            f"Protected {len(protected)} ideograms with italicized pinyin "
            f"(first-occurrence footnotes preserved): {sorted(protected)}"
        )
        return protected

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
    )
    def score_footnotes_batch(
        self, footnotes: List[Dict[str, Any]]
    ) -> List[TrivialityScore]:
        """Score a batch of footnotes for triviality using OpenAI."""
        user_content = "Assess these footnotes for triviality:\n\n"
        for idx, fn in enumerate(footnotes):
            user_content += (
                f"--- Footnote {idx} ---\n"
                f"Term: {fn['ideogram']} ({fn.get('pinyin', '')})\n"
                f"Explanation: {fn['explanation']}\n"
                f"Content type: {fn['content_type']}\n"
                f"Context: {fn['context_snippet'][:200]}\n\n"
            )

        response = self.client.chat(LLMRequest(
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            model=self.config.model,
            temperature=self.config.temperature,
            json_mode=True,
        ))

        result_data = response.parsed
        assessments = result_data.get("assessments", [])

        scores = []
        for idx, fn in enumerate(footnotes):
            if idx < len(assessments):
                a = assessments[idx]
                scores.append(
                    TrivialityScore(
                        footnote_key=fn.get("key", idx + 1),
                        ideogram=fn["ideogram"],
                        explanation=fn["explanation"],
                        triviality_score=int(a.get("triviality_score", 0)),
                        cultural_specificity_score=int(
                            a.get("cultural_specificity_score", 100)
                        ),
                        should_remove=bool(a.get("should_remove", False)),
                        reasoning=a.get("reasoning", ""),
                    )
                )
            else:
                # Fallback: preserve if API didn't return enough results
                scores.append(
                    TrivialityScore(
                        footnote_key=fn.get("key", idx + 1),
                        ideogram=fn["ideogram"],
                        explanation=fn["explanation"],
                        triviality_score=0,
                        cultural_specificity_score=100,
                        should_remove=False,
                        reasoning="Fallback: no API assessment returned",
                    )
                )

        return scores

    def score_all_footnotes(
        self, footnotes: List[Dict[str, Any]]
    ) -> Dict[str, TrivialityScore]:
        """Score all footnotes in batches. Returns mapping of block_id:key -> score."""
        scores = {}
        total_batches = (
            (len(footnotes) + self.config.batch_size - 1) // self.config.batch_size
        )

        with tqdm(total=len(footnotes), desc="Scoring footnotes") as pbar:
            for i in range(0, len(footnotes), self.config.batch_size):
                batch = footnotes[i : i + self.config.batch_size]
                batch_num = i // self.config.batch_size + 1
                logger.info(f"Scoring batch {batch_num}/{total_batches}")

                try:
                    batch_scores = self.score_footnotes_batch(batch)
                    for fn, score in zip(batch, batch_scores):
                        key = f"{fn['block_id']}:{fn.get('key', 0)}"
                        scores[key] = score
                        self.result.scores.append(score)
                except Exception as e:
                    logger.error(f"Failed to score batch {batch_num}: {e}")
                    # Preserve on failure
                    for fn in batch:
                        key = f"{fn['block_id']}:{fn.get('key', 0)}"
                        fallback = TrivialityScore(
                            footnote_key=fn.get("key", 0),
                            ideogram=fn["ideogram"],
                            explanation=fn["explanation"],
                            triviality_score=0,
                            cultural_specificity_score=100,
                            should_remove=False,
                            reasoning=f"Preserved due to scoring error: {e}",
                        )
                        scores[key] = fallback
                        self.result.scores.append(fallback)

                pbar.update(len(batch))

        self.result.analyzed_count = len(scores)
        return scores

    def should_remove(self, score: TrivialityScore) -> bool:
        """Determine if a footnote should be removed based on scores.

        Removal logic:
        - If model says remove AND triviality >= threshold → remove
          (trust the model's judgment over cultural score)
        - If triviality >= 80 regardless of should_remove → remove
          (catch cases where model was inconsistent)
        - Only preserve if cultural_specificity is very high (>= 80)
          AND triviality is moderate (< 70)
        """
        if score.triviality_score >= 80:
            # Very trivial — only preserve if genuinely high cultural value
            # AND model didn't flag for removal
            if score.cultural_specificity_score >= 80 and not score.should_remove:
                return False
            return True
        if score.should_remove and score.triviality_score >= self.config.triviality_threshold:
            return True
        return False

    def remove_trivial_footnotes(
        self,
        data: Dict[str, Any],
        scores: Dict[str, TrivialityScore],
    ) -> Dict[str, Any]:
        """
        Remove scored-trivial footnotes, deduplicate by ideogram across
        the entire work, and renumber remaining ones.

        Deduplication: only the first occurrence of each ideogram's footnote
        is kept. Subsequent occurrences are removed as duplicates regardless
        of triviality score.

        Args:
            data: Full work JSON
            scores: Triviality scores keyed by "block_id:key"

        Returns:
            Modified JSON data
        """
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

        # Track ideograms across the entire work for deduplication
        seen_ideograms: set = set()

        for chapter in tqdm(chapters, desc="Removing trivial footnotes"):
            for block in chapter.get("content_blocks", []):
                block_id = block.get("id", "unknown")
                footnotes = block.get("footnotes", [])
                if not footnotes:
                    continue

                filtered = []
                removed_keys = set()

                for fn in footnotes:
                    ideogram = fn.get("ideogram", "")
                    key = f"{block_id}:{fn.get('key', 0)}"
                    score = scores.get(key)

                    # Protect first occurrence of italicized-pinyin terms
                    if ideogram in self._protected_ideograms and ideogram not in seen_ideograms:
                        filtered.append(fn)
                        self.result.preserved_count += 1
                        seen_ideograms.add(ideogram)
                        continue

                    # Dedup: remove if this ideogram was already footnoted
                    if ideogram and ideogram in seen_ideograms:
                        removed_keys.add(fn.get("key"))
                        self.result.removed_footnotes.append({
                            "ideogram": ideogram,
                            "explanation": fn.get("explanation", ""),
                            "type": "DUPLICATE",
                            "reasoning": f"Duplicate: '{ideogram}' already footnoted earlier in work",
                            "block_id": block_id,
                        })
                        self.result.removed_count += 1
                        self.result.duplicate_count += 1
                        continue

                    # Triviality: remove if scored trivial
                    if score and self.should_remove(score):
                        removed_keys.add(fn.get("key"))
                        self.result.removed_footnotes.append({
                            "ideogram": ideogram,
                            "explanation": fn.get("explanation", ""),
                            "triviality_score": score.triviality_score,
                            "cultural_specificity_score": score.cultural_specificity_score,
                            "reasoning": score.reasoning,
                            "block_id": block_id,
                        })
                        self.result.removed_count += 1
                    else:
                        filtered.append(fn)
                        self.result.preserved_count += 1
                        # Mark this ideogram as seen
                        if ideogram:
                            seen_ideograms.add(ideogram)

                # Renumber kept footnotes
                old_to_new = {}
                for idx, fn in enumerate(filtered, start=1):
                    old_to_new[fn.get("key")] = idx
                    fn["key"] = idx

                block["footnotes"] = filtered

                # Update inline markers
                translated = block.get("translated_content", "")
                if translated and (removed_keys or old_to_new):
                    block["translated_content"] = _remap_markers(
                        translated, old_to_new, removed_keys
                    )

        # Compute averages
        removed_scores = [
            s for s in self.result.scores if self.should_remove(s)
        ]
        preserved_scores = [
            s for s in self.result.scores if not self.should_remove(s)
        ]

        if removed_scores:
            self.result.avg_triviality_removed = sum(
                s.triviality_score for s in removed_scores
            ) / len(removed_scores)

        if preserved_scores:
            self.result.avg_cultural_preserved = sum(
                s.cultural_specificity_score for s in preserved_scores
            ) / len(preserved_scores)

        return data

    PHASE3_PROMPT = """You are a ruthless footnote editor for a translated Chinese wuxia novel. You will receive a list of footnotes (Chinese term + English explanation). For EACH one, decide: REMOVE or KEEP.

REMOVE if the explanation:
- Just translates the Chinese into English (e.g., 駿馬 = "a fine steed" — the reader already sees "horse" in the English text)
- Describes a fictional character (e.g., "A palace guard", "a young woman skilled in martial arts")
- Explains a universal emotion, action, or body language (e.g., "sighing deeply", "shaking one's head", "cry of pain")
- Describes something obvious (e.g., "a mountain", "pine branches", "the sleeve of a garment")
- Is meta-narrative (e.g., "next chapter to be unfolded", "what happens next")
- Provides no genuinely specific cultural information

KEEP if the explanation:
- Names a REAL historical person with dates or context
- Explains a specific martial arts technique, form, school, or named move (e.g., "Thousand-Pound Fist", "Bird Flip", "Whirlwind Palm")
- Names or describes acupoints, pressure points, or meridian concepts
- Describes a real Buddhist/Taoist/Confucian concept
- Identifies a real geographic location with historical significance
- Explains a genuine cultural practice unfamiliar to Western readers
- Provides specific historical context (dynasty names, political events, reign periods)
- Explains traditional medicine, qi cultivation, internal energy, or acupuncture concepts
- Describes a named weapon, lightness skill, grappling technique, or martial style

DEFAULT: When in doubt, REMOVE. The reader is intelligent. Only KEEP footnotes that teach something a well-read English speaker genuinely would not know.

For each footnote, return a JSON object: {"index": N, "verdict": "REMOVE" or "KEEP", "reason": "brief"}
Return valid JSON as: {"verdicts": [...]}"""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
    )
    def _review_batch(self, batch: List[Dict[str, str]]) -> List[Dict]:
        """Send a batch of ideogram+explanation pairs for context-free review."""
        user_content = "Review these footnotes. For each, decide REMOVE or KEEP. Return json:\n\n"
        for idx, fn in enumerate(batch):
            user_content += (
                f"[{idx}] {fn['ideogram']}: {fn['explanation']}\n"
            )

        response = self.client.chat(LLMRequest(
            messages=[
                {"role": "system", "content": self.PHASE3_PROMPT},
                {"role": "user", "content": user_content},
            ],
            model=self.config.model,
            temperature=0.1,  # Very low for consistency
            json_mode=True,
        ))
        return response.parsed.get("verdicts", [])

    def review_survivors_by_ideogram(self, data: Dict[str, Any]) -> int:
        """
        Phase 3: Context-free review of all surviving footnotes.

        Collects unique ideogram→explanation pairs across the work, sends them
        to the API without paragraph context, and removes those judged trivial.
        Each unique ideogram is only reviewed once; if removed, ALL occurrences
        across all blocks are removed.

        Returns the number of footnotes removed.
        """
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

        # Collect unique ideogram → explanation (first occurrence wins)
        unique_fns: Dict[str, str] = {}
        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                for fn in block.get("footnotes", []):
                    ideo = fn.get("ideogram", "")
                    if ideo and ideo not in unique_fns:
                        unique_fns[ideo] = fn.get("explanation", "")

        if not unique_fns:
            return 0

        logger.info(f"Phase 3: Reviewing {len(unique_fns)} unique ideograms")

        # Batch and review
        items = [{"ideogram": k, "explanation": v} for k, v in unique_fns.items()]
        remove_ideograms: set = set()

        batch_size = self.config.batch_size
        total_batches = (len(items) + batch_size - 1) // batch_size

        with tqdm(total=len(items), desc="Phase 3 review") as pbar:
            for i in range(0, len(items), batch_size):
                batch = items[i:i + batch_size]
                batch_num = i // batch_size + 1

                try:
                    verdicts = self._review_batch(batch)
                    for idx, item in enumerate(batch):
                        if idx < len(verdicts):
                            v = verdicts[idx]
                            if v.get("verdict", "").upper() == "REMOVE":
                                remove_ideograms.add(item["ideogram"])
                except Exception as e:
                    logger.error(f"Phase 3 batch {batch_num} failed: {e}")

                pbar.update(len(batch))

        # Exclude protected ideograms (italicized-pinyin first occurrences)
        protected_in_phase3 = remove_ideograms & self._protected_ideograms
        if protected_in_phase3:
            logger.info(
                f"Phase 3: Protecting {len(protected_in_phase3)} italicized-pinyin "
                f"ideograms from removal: {sorted(protected_in_phase3)}"
            )
            remove_ideograms -= protected_in_phase3

        if not remove_ideograms:
            logger.info("Phase 3: No additional footnotes to remove")
            return 0

        logger.info(f"Phase 3: Removing {len(remove_ideograms)} ideograms across all blocks")

        # Remove from all blocks
        removed_total = 0
        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                footnotes = block.get("footnotes", [])
                if not footnotes:
                    continue

                filtered = []
                removed_keys = set()

                for fn in footnotes:
                    ideo = fn.get("ideogram", "")
                    if ideo in remove_ideograms:
                        removed_keys.add(fn.get("key"))
                        self.result.removed_footnotes.append({
                            "ideogram": ideo,
                            "explanation": fn.get("explanation", "")[:80],
                            "type": "PHASE3_REVIEW",
                            "block_id": block.get("id", "unknown"),
                        })
                        self.result.removed_count += 1
                        removed_total += 1
                    else:
                        filtered.append(fn)

                if removed_keys:
                    old_to_new = {}
                    for idx, fn in enumerate(filtered, start=1):
                        old_to_new[fn.get("key")] = idx
                        fn["key"] = idx
                    block["footnotes"] = filtered

                    translated = block.get("translated_content", "")
                    if translated:
                        block["translated_content"] = _remap_markers(
                            translated, old_to_new, removed_keys
                        )

        return removed_total

    def remove_suppressed_footnotes(
        self,
        data: Dict[str, Any],
        suppress_path: Optional[Path] = None,
    ) -> int:
        """
        Phase 1: Programmatically remove footnotes whose ideogram matches
        the suppress list.  No API calls.  Fast and deterministic.

        Also removes footnotes with empty explanations.

        Returns the number of footnotes removed.
        """
        from processors.translation_prompts import get_suppress_ideograms

        suppressed = get_suppress_ideograms(suppress_path)
        if not suppressed:
            logger.warning("Suppress list is empty — skipping Phase 1")
            return 0

        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        removed_total = 0

        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                footnotes = block.get("footnotes", [])
                if not footnotes:
                    continue

                filtered = []
                removed_keys = set()

                for fn in footnotes:
                    ideogram = fn.get("ideogram", "")
                    explanation = fn.get("explanation", "")

                    # Protect first occurrence of italicized-pinyin terms
                    if ideogram in self._protected_ideograms and ideogram not in self._protected_seen:
                        self._protected_seen.add(ideogram)
                        filtered.append(fn)
                        continue

                    if ideogram in suppressed or not explanation.strip():
                        removed_keys.add(fn.get("key"))
                        self.result.removed_footnotes.append({
                            "ideogram": ideogram,
                            "explanation": explanation[:80],
                            "type": "SUPPRESS_LIST",
                            "block_id": block.get("id", "unknown"),
                        })
                        self.result.removed_count += 1
                        removed_total += 1
                    else:
                        filtered.append(fn)

                if removed_keys:
                    # Renumber
                    old_to_new = {}
                    for idx, fn in enumerate(filtered, start=1):
                        old_to_new[fn.get("key")] = idx
                        fn["key"] = idx
                    block["footnotes"] = filtered

                    translated = block.get("translated_content", "")
                    if translated:
                        block["translated_content"] = _remap_markers(
                            translated, old_to_new, removed_keys
                        )

        return removed_total

    def remove_heuristic_trivial(self, data: Dict[str, Any]) -> int:
        """
        Phase 1.5: Programmatic heuristic removal — no API calls.

        Removes footnotes that are clearly trivial based on pattern matching:
        - Fictional character name explanations ("A personal name", "A character's name")
        - Frequency-based character name detection (2-3 char ideograms appearing 3+
          times in the chapter with no historical signals in explanation)
        - Pure translations with no cultural content (short explanations with no
          dates, dynasty names, historical references)
        - Emotion/action descriptions

        Returns the number of footnotes removed.
        """
        # Patterns indicating fictional character name footnotes
        _CHAR_NAME_PATTERNS = [
            r"(?i)^a\s+(personal|character'?s?|fictional|proper)\s+name",
            r"(?i)^(personal|character|proper)\s+name",
            r"(?i)a\s+character\s+in\s+the\s+(story|novel|narrative)",
            r"(?i)^refers?\s+to\s+(a|the)\s+(character|person|protagonist|antagonist|individual|figure)",
            r"(?i)^name\s+of\s+a\s+(fictional|character|martial)",
            # Broader patterns for character descriptions
            r"(?i)^a\s+(young\s+)?(woman|man|girl|boy|lady|lord|warrior|guard|soldier|elder|monk|nun|hero|heroine|swordsman|swordswoman|fighter|martial\s+artist)\b",
            r"(?i)^(young\s+)?(woman|man|warrior|hero|heroine|guard|palace\s+guard|swordsman|martial\s+artist)\b",
            # Patterns from literary-register prompt output
            r"(?i)^a\s+proper\s+(name|noun)",
            r"(?i)personal\s+identity\s+into\s+a\s+(mythic|heroic)",
            r"(?i)^an?\s+(esteemed|renowned|skilled|fearsome|formidable)\s+(martial|warrior|fighter|swordsman)",
            r"(?i)(protagonist|antagonist|challenger)\s+within\s+the\s+ji[aā]ngh[uú]",
            # Dramatis personae: character introductions via sobriquet/honorific
            r"(?i)(known\s+by\s+(the\s+)?(honorific|sobriquet|nickname|alias|epithet|title)|known\s+as\s+['\"])",
            r"(?i)^['\"]?[A-Z][\w-]+['\"]?\s+is\s+the\s+(martial\s+)?sobriquet\b",
            r"(?i)sobriquet\s+of\s+",
            r"(?i)^a\s+(female|male)\s+(fighter|warrior|swordsman|swordswoman)\s+known\b",
        ]
        _char_re = [re.compile(p) for p in _CHAR_NAME_PATTERNS]

        # Patterns indicating a footnote has genuine cultural content (preserve)
        _CULTURAL_SIGNALS = re.compile(
            r"(?i)(dynasty|emperor|reign|century|\bBCE\b|\bCE\b|\bAD\b|\bBC\b|"
            r"\d{3,4}\s*[-–]\s*\d{3,4}|"  # date ranges like 1661-1722
            r"buddhis[mt]|taois[mt]|confuci|daois[mt]|"
            r"bodhisattva|sutra|temple|monastery|"
            r"martial\s+arts?\s+technique|martial\s+arts?\s+style|"
            r"classic(al)?\s+(chinese|poem|text|work)|"
            r"literary\s+(allusion|reference|form)|"
            r"traditional\s+(chinese|medicine|practice|custom)|"
            r"historical|ancient\s+china|imperial|"
            r"acupuncture|meridian|qi\s+cultivation|"
            r"ritual|ceremony|rite|"
            # Ethnic/political groups
            r"mongol|turkic|tatar|manchu|jurchen|tibetan|uyghur|"
            r"han\s+chinese|ethnic\s+group|"
            r"tribe|faction|horde|khanate|"
            # Wuxia relationship terms
            r"martial\s+(brother|sister|uncle|nephew|niece|aunt)|"
            r"senior\s+martial|junior\s+martial|fellow\s+disciple|"
            r"sect\s+leader|martial\s+arts?\s+school|"
            # Legal/government/military ranks
            r"punishment|exile|banishment|execution|penal|"
            r"magistrate|governor|prefect|chancellor|minister|"
            r"commander|general|garrison|"
            # Specific cultural practices
            r"concubine|betrothal|dowry|filial|mourning\s+period|"
            r"kowtow|prostrat|incense|"
            # Named techniques/weapons/martial moves
            r"technique|stance|form\s+of|style\s+of|school\s+of|"
            r"palm\s+(technique|method|strike|art|style)|"
            r"fist\s+(technique|method|style|routine)|"
            r"sabre\s+(technique|method|style)|sword\s+(technique|art|style)|"
            r"blade\s+(technique|system|method)|"
            r"(named\s+after|trigram|bagua|tàijí|taiji)|"
            r"lightness\s+(skill|art|technique)|"
            r"grappl|seiz|joint\s+lock|"
            r"acupoint|pressure\s+point|vital\s+point|meridian\s+system|"
            r"internal\s+(energy|skill|cultivation|style)|neigong|"
            r"acrobatic\s+technique|"
            r"poison|antidote|venom)"
        )

        # Patterns indicating trivial emotion/action/description explanations
        _TRIVIAL_PATTERNS = [
            # Emotions and psychological states
            r"(?i)^(feeling|expressing|showing|indicating|harboring)\s+(a\s+)?(sense\s+of\s+)?"
            r"(joy|sadness|anger|fear|embarrass|shy|warm|cold|happy|sorrow|surprise|shock|"
            r"anxiety|worry|concern|suspicion|doubt|rage|fury|pain|distress)",
            r"(?i)(secretly\s+harboring|begun?\s+to\s+suspect|indicating\s+(the\s+)?emotional)",
            r"(?i)^(expressions?\s+of\s+(surprise|shock|anger|joy|sorrow|pain))",
            r"(?i)^(an?\s+(almost\s+)?involuntary\s+cry)",
            # Physical actions
            r"(?i)^(reaching|turning|looking|glancing|walking|running|sitting|standing|bowing)",
            r"(?i)^(shaking|sighing|pacing|withdrew|resting|coughing|gasping|weeping|crying)",
            r"(?i)^(continuously\s+coughing|pacing\s+around|shaking\s+one)",
            r"(?i)^(repeatedly\s+(glancing|looking|checking))",
            r"(?i)^(to\s+(rest|sleep|sigh|weep|flatter|reveal|expose|mediate|attack))\b",
            r"(?i)^(withdrew|retreated|departed)\s+from",
            r"(?i)^(has\s+(already\s+)?(discerned|noticed|detected|realized))",
            r"(?i)^(he\s+was\s+aware|she\s+was\s+aware|indicating\s+)",
            # Quantities and simple descriptions
            r"(?i)^(two|three|four|five|six|seven|eight|nine|ten)\s+(person|people|individual)",
            r"(?i)^(a|the)\s+(sleeve|bottle|cup|bowl|table|chair|door|gate|horse|sword|blade"
            r"|mountain|hill|cave|forest|tree|plant|cloud|wind|rain|snow|river|lake)\b",
            r"(?i)^(plants?\s+and\s+trees|morning\s+clouds|distant\s+place|very\s+dirty)",
            # Grammar/linguistics notes
            r"(?i)^(a\s+modal\s+particle|literally\s+means?\s+')",
            # Meta-narrative
            r"(?i)^(literally\s+['\"]next\s+chapter)",
            r"(?i)(a\s+common\s+phrase.*end\s+of\s+(a\s+)?(story|chapter))",
            # Pure transliterations with no context
            r"(?i)^(let\s+or\s+allow|short\s+for\s+|refers?\s+to\s+the\s+region)",
            # Obvious descriptions
            r"(?i)^(extremely\s+powerful|lingering\s+(sound|echo)|a\s+polite\s+way)",
            r"(?i)^(his\s+pulse\s+has|emphasiz(es?|ing)\s+that)",
            r"(?i)^(to\s+attack\s+in\s+greater|to\s+toast|to\s+drink\s+all)",
            # Actions/gestures
            r"(?i)^(smiled?\s+broadly|made\s+a\s+gesture|indicates?\s+repeatedly)",
            r"(?i)^(willing\s+to\s+die|a\s+humble\s+way|a\s+respectful\s+way)",
            r"(?i)^(a\s+(common|traditional)\s+(sign|way)\s+of)",
            r"(?i)(urging\s+the\s+focus|refers?\s+to\s+the\s+quote)",
            # Onomatopoeia and simple translations
            r"(?i)^(gibberish|whinnying|onomatop)",
            r"(?i)^(muscle\s+cramps|involuntary)",
        ]
        _trivial_re = [re.compile(p) for p in _TRIVIAL_PATTERNS]

        # Historical figure signals — if explanation has these, preserve even if
        # the ideogram looks like a character name
        _HISTORICAL_SIGNALS = re.compile(
            r"(?i)(dynasty|emperor|reign|historical|real|actual|famous|"
            r"\d{3,4}\s*[-–]\s*\d{3,4}|"
            r"\bBCE\b|\bCE\b|\bAD\b|\bBC\b|"
            r"\bqing\b|\bming\b|\bsong\b|\btang\b|\byuan\b|\bjin\b|\bsui\b|"
            r"poet|scholar|general|minister|chancellor|"
            r"literary\s+figure|prime\s+minister)"
        )

        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        removed_total = 0

        # Build frequency map at book level: count how many times each
        # potential name ideogram appears across ALL source text
        book_source = ""
        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                book_source += block.get("content", "")

        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                footnotes = block.get("footnotes", [])
                if not footnotes:
                    continue

                filtered = []
                removed_keys = set()

                for fn in footnotes:
                    explanation = fn.get("explanation", "")
                    ideogram = fn.get("ideogram", "")

                    # Protect first occurrence of italicized-pinyin terms
                    if ideogram in self._protected_ideograms and ideogram in self._protected_seen:
                        # Already preserved once — subsequent occurrences can be removed
                        pass
                    elif ideogram in self._protected_ideograms:
                        self._protected_seen.add(ideogram)
                        filtered.append(fn)
                        continue

                    remove = False
                    reason = ""

                    # Check fictional character name patterns
                    for pat in _char_re:
                        if pat.search(explanation):
                            # But preserve if historical signals present
                            if not _HISTORICAL_SIGNALS.search(explanation):
                                remove = True
                                reason = "HEURISTIC_CHAR_NAME"
                            break

                    # Frequency-based character name detection:
                    # Ideograms appearing multiple times in source text
                    # with no historical/cultural signals → likely fictional name
                    # 2-3 chars: threshold 3 (common names)
                    # 4+ chars: threshold 2 (compound names are very specific)
                    if not remove and 2 <= len(ideogram) <= 5:
                        freq = book_source.count(ideogram)
                        threshold = 2 if len(ideogram) >= 4 else 3
                        if freq >= threshold:
                            if not _HISTORICAL_SIGNALS.search(explanation):
                                if not _CULTURAL_SIGNALS.search(explanation):
                                    remove = True
                                    reason = "HEURISTIC_FREQ_NAME"

                    # Check trivial emotion/action patterns
                    if not remove:
                        for pat in _trivial_re:
                            if pat.search(explanation):
                                # But preserve if it has cultural signals
                                if not _CULTURAL_SIGNALS.search(explanation):
                                    remove = True
                                    reason = "HEURISTIC_TRIVIAL_ACTION"
                                    break

                    # Check short explanations with no cultural signals
                    # (likely just translations or obvious descriptions)
                    if not remove and len(explanation) < 80:
                        if not _CULTURAL_SIGNALS.search(explanation):
                            # Short explanation with no cultural content
                            remove = True
                            reason = "HEURISTIC_SHORT_NO_CULTURE"

                    if remove:
                        removed_keys.add(fn.get("key"))
                        self.result.removed_footnotes.append({
                            "ideogram": ideogram,
                            "explanation": explanation[:80],
                            "type": reason,
                            "block_id": block.get("id", "unknown"),
                        })
                        self.result.removed_count += 1
                        removed_total += 1
                    else:
                        filtered.append(fn)

                if removed_keys:
                    old_to_new = {}
                    for idx, fn in enumerate(filtered, start=1):
                        old_to_new[fn.get("key")] = idx
                        fn["key"] = idx
                    block["footnotes"] = filtered

                    translated = block.get("translated_content", "")
                    if translated:
                        block["translated_content"] = _remap_markers(
                            translated, old_to_new, removed_keys
                        )

        return removed_total

    def process_file(
        self,
        input_path: Path,
        output_path: Path,
        dry_run: bool = False,
        suppress_path: Optional[Path] = None,
    ) -> TrivialityResult:
        """
        Process a single JSON file with three-phase removal.

        Phase 1: Programmatic suppress-list removal (no API calls).
        Phase 1.5: Heuristic pattern removal (character names, short translations, actions — no API).
        Phase 2: AI-powered triviality scoring on remaining footnotes.

        Args:
            input_path: Path to input JSON file
            output_path: Path to output JSON file
            dry_run: If True, score but don't write output
            suppress_path: Path to suppress list JSON (uses default if None)

        Returns:
            TrivialityResult with statistics
        """
        logger.info(f"Processing: {input_path}")

        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Backup
        if self.config.create_backup and not dry_run:
            backup_path = input_path.with_suffix(".json.triviality_backup")
            if not backup_path.exists():
                with open(backup_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.info(f"Created backup: {backup_path}")

        # Count total footnotes before any removal
        all_fns = self.extract_footnotes_with_context(data)
        self.result.total_footnotes = len(all_fns)
        logger.info(f"Found {len(all_fns)} total footnotes")

        if not all_fns:
            logger.warning("No footnotes found")
            return self.result

        # --- Phase 0: Build protected set (italicized pinyin terms) ---
        self._protected_ideograms = self._build_protected_set(data)
        self._protected_seen: set = set()

        # --- Phase 1: Programmatic suppress-list removal ---
        logger.info("Phase 1: Removing suppress-list matches (no API)...")
        suppressed_count = self.remove_suppressed_footnotes(data, suppress_path)
        logger.info(f"Phase 1 removed {suppressed_count} footnotes via suppress list")

        # --- Phase 1.5: Heuristic pattern removal ---
        logger.info("Phase 1.5: Removing heuristic-trivial footnotes (no API)...")
        heuristic_count = self.remove_heuristic_trivial(data)
        logger.info(f"Phase 1.5 removed {heuristic_count} footnotes via heuristics")

        # --- Phase 2: AI scoring on remainder ---
        remaining_fns = self.extract_footnotes_with_context(data)
        logger.info(f"Phase 2: Scoring {len(remaining_fns)} remaining footnotes via API...")

        if remaining_fns:
            scores = self.score_all_footnotes(remaining_fns)

            if not dry_run:
                logger.info("Removing AI-scored trivial footnotes...")
                data = self.remove_trivial_footnotes(data, scores)
        else:
            logger.info("No remaining footnotes to score")

        # --- Phase 3: Context-free review of survivors by ideogram ---
        if not dry_run:
            logger.info("Phase 3: Context-free review of surviving footnotes by ideogram...")
            phase3_removed = self.review_survivors_by_ideogram(data)
            logger.info(f"Phase 3 removed {phase3_removed} footnotes via context-free review")

            # Dedup within each block (same ideogram footnoted twice)
            intra_deduped = _dedup_intra_block(data)
            if intra_deduped:
                logger.info(f"Removed {intra_deduped} intra-block duplicate footnotes")

            # Reposition misplaced markers to be adjacent to their term
            # Footnotes whose term can't be found in the text are removed
            repos_count, unanchored_count = _reposition_markers(data)
            if repos_count:
                logger.info(f"Repositioned {repos_count} footnote markers")
            if unanchored_count:
                logger.info(f"Removed {unanchored_count} unanchored footnotes (term not in text)")
                self.result.removed_count += unanchored_count

            # Renumber footnotes continuously across each chapter
            _renumber_chapter_continuous(data)
            logger.info("Renumbered footnotes continuously per chapter")

            # Sanitize orphan markers (from source translation or removal gaps)
            orphans_fixed = _sanitize_orphan_markers(data)
            if orphans_fixed:
                logger.info(f"Sanitized orphan markers in {orphans_fixed} blocks")

            # AI marker-position verification (cheap nano pass on survivors)
            logger.info("Verifying footnote marker positions via AI...")
            ai_repos = _ai_verify_marker_positions(data, self.client)
            if ai_repos:
                logger.info(f"AI repositioned {ai_repos} misplaced markers")
                # Renumber again after AI repositioning
                _renumber_chapter_continuous(data)
                orphans_fixed_2 = _sanitize_orphan_markers(data)
                if orphans_fixed_2:
                    logger.info(f"Post-AI: sanitized {orphans_fixed_2} orphan markers")

            # Validate integrity
            validation = validate_footnote_integrity(data)
            self.result.validation_passed = validation["passed"]

            if not validation["passed"]:
                logger.error(
                    f"Validation FAILED after removal: {validation['errors'][:5]}"
                )
                logger.error("Output NOT written due to validation failure")
                return self.result

            # Write output
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Wrote cleaned file to: {output_path}")
        else:
            to_remove = sum(1 for s in self.result.scores if self.should_remove(s))
            logger.info(
                f"Dry run: would remove {to_remove} more via AI "
                f"(plus {suppressed_count} already removed via suppress list)"
            )
            self.result.validation_passed = True

        return self.result


def _dedup_intra_block(data: Dict[str, Any]) -> int:
    """Remove duplicate ideograms within the same block (keep first occurrence)."""
    removed_total = 0
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
    for chapter in chapters:
        for block in chapter.get("content_blocks", []):
            footnotes = block.get("footnotes", [])
            if not footnotes:
                continue

            seen = set()
            filtered = []
            removed_keys = set()

            for fn in footnotes:
                ideogram = fn.get("ideogram", "")
                if ideogram in seen:
                    removed_keys.add(fn.get("key"))
                    removed_total += 1
                else:
                    seen.add(ideogram)
                    filtered.append(fn)

            if removed_keys:
                old_to_new = {}
                for idx, fn in enumerate(filtered, start=1):
                    old_to_new[fn.get("key")] = idx
                    fn["key"] = idx
                block["footnotes"] = filtered

                translated = block.get("translated_content", "")
                if translated:
                    block["translated_content"] = _remap_markers(
                        translated, old_to_new, removed_keys
                    )

    return removed_total


def _renumber_chapter_continuous(data: Dict[str, Any]) -> None:
    """Renumber footnotes continuously across each chapter (not per-block)."""
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

    for chapter in chapters:
        chapter_counter = 0
        for block in chapter.get("content_blocks", []):
            footnotes = block.get("footnotes", [])
            if not footnotes:
                continue

            old_to_new = {}
            for fn in footnotes:
                old_key = fn.get("key")
                chapter_counter += 1
                old_to_new[old_key] = chapter_counter
                fn["key"] = chapter_counter

            # Remap markers in translated text
            translated = block.get("translated_content", "")
            if translated and old_to_new:
                block["translated_content"] = _remap_markers(
                    translated, old_to_new, set()
                )


def _strip_tones(s: str) -> str:
    """Strip tone marks from pinyin for fuzzy matching."""
    tone_map = str.maketrans(
        "āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ",
        "aaaaeeeeiiiioooouuuuüüüü",
    )
    return s.translate(tone_map)


def _is_word_boundary(text: str, start: int, end: int) -> bool:
    """Check that match at text[start:end] is at word boundaries (not inside another word)."""
    # Allow tone-marked chars as word chars
    _word_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                      "āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ")
    if start > 0 and text[start - 1] in _word_chars:
        return False
    if end < len(text) and text[end] in _word_chars:
        return False
    return True


def _find_word(haystack: str, needle: str, start: int = 0) -> int:
    """Find needle in haystack with word-boundary check. Returns index or -1."""
    pos = start
    while True:
        idx = haystack.find(needle, pos)
        if idx == -1:
            return -1
        if _is_word_boundary(haystack, idx, idx + len(needle)):
            return idx
        pos = idx + 1


def _find_term_in_text(
    text: str,
    pinyin: str,
    explanation: str,
    ideogram: str = "",
    source_text: str = "",
) -> Tuple[int, int]:
    """
    Find a footnoted term in the translated text by searching for:
    1. Full pinyin (exact, then case-insensitive, then tone-stripped)
    2. First word of multi-word pinyin (case-insensitive, tone-stripped)
    3. English term extracted from explanation (pre-separator text)
    4. Key English nouns/phrases from explanation
    5. Positional mapping from source text (ideogram position → proportional)

    All searches enforce word boundaries to avoid matching inside other words.
    Also strips markdown italic markers (*word*) and quotes before searching.

    Returns (start_idx, end_idx) or (-1, -1) if not found.
    """
    # Pre-process: strip ALL asterisks and normalize quotes for searching
    search_text = text.replace("*", "")
    search_text = search_text.replace("\u201c", '"').replace("\u201d", '"')
    search_text = search_text.replace("\u2018", "'").replace("\u2019", "'")
    lower_search = search_text.lower()
    tone_stripped_search = _strip_tones(lower_search)

    # Strategy 1: Pinyin match
    if pinyin:
        pinyin_lower = pinyin.lower()
        pinyin_stripped = _strip_tones(pinyin_lower)

        # Exact match (with word boundary)
        idx = _find_word(search_text, pinyin)
        if idx != -1:
            return idx, idx + len(pinyin)

        # Case-insensitive
        idx = _find_word(lower_search, pinyin_lower)
        if idx != -1:
            return idx, idx + len(pinyin)

        # Tone-stripped (handles LLM omitting tone marks)
        if pinyin_stripped != pinyin_lower:
            idx = _find_word(tone_stripped_search, pinyin_stripped)
            if idx != -1:
                return idx, idx + len(pinyin)

        # First word of multi-word pinyin (case-insensitive + tone-stripped)
        if " " in pinyin:
            words = pinyin.split()
            first = words[0]
            if len(first) > 2:
                first_lower = first.lower()
                first_stripped = _strip_tones(first_lower)

                # Try case-insensitive first
                idx = _find_word(lower_search, first_lower)
                if idx == -1:
                    idx = _find_word(tone_stripped_search, first_stripped)

                if idx != -1:
                    # Try to find the last word nearby to get full span
                    last = words[-1]
                    last_lower = last.lower()
                    end_idx = _find_word(lower_search, last_lower, idx)
                    if end_idx == -1:
                        end_idx = _find_word(
                            tone_stripped_search,
                            _strip_tones(last_lower), idx
                        )
                    if end_idx != -1 and end_idx - idx < 80:
                        return idx, end_idx + len(last)
                    return idx, idx + len(first)

    # Strategy 2: English term from explanation
    if explanation:
        # Try text before first separator
        for sep in [":", ";", ",", "—", "–"]:
            if sep in explanation:
                candidate = explanation.split(sep)[0].strip()
                # Clean up articles
                for prefix in ["The ", "A ", "An "]:
                    if candidate.startswith(prefix):
                        candidate = candidate[len(prefix):]
                if 3 <= len(candidate) <= 50:
                    idx = _find_word(lower_search, candidate.lower())
                    if idx != -1:
                        return idx, idx + len(candidate)
                break

        # Try capitalized words/phrases from explanation (proper nouns/terms)
        cap_words = re.findall(
            r"[A-Z][a-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]+"
            r"(?:\s+[A-Z][a-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]+)*",
            explanation,
        )
        for cw in cap_words:
            if len(cw) > 3:
                idx = _find_word(lower_search, cw.lower())
                if idx != -1:
                    return idx, idx + len(cw)
                # Tone-stripped fallback
                idx = _find_word(tone_stripped_search, _strip_tones(cw.lower()))
                if idx != -1:
                    return idx, idx + len(cw)

        # Strategy 3: Common English translations of the concept
        # E.g., "Buddhist practitioners" → search for "Buddhist"
        common_terms = re.findall(r"\b([A-Z][a-z]{3,})\b", explanation)
        for term in common_terms:
            if term.lower() in (
                "this", "that", "they", "them", "their", "these",
                "often", "also", "here", "used", "known", "refers",
                "name", "from", "with", "were", "have", "been",
            ):
                continue
            idx = _find_word(lower_search, term.lower())
            if idx != -1:
                return idx, idx + len(term)

    # Strategy 5: Positional mapping from source text
    # Find ideogram in Chinese source, map proportionally to English text,
    # then place at nearest sentence boundary.
    if ideogram and source_text:
        src_idx = source_text.find(ideogram)
        if src_idx != -1:
            ratio = (src_idx + len(ideogram)) / max(len(source_text), 1)
            approx_pos = int(ratio * len(search_text))
            # Snap to word boundary if we landed mid-word
            if (0 < approx_pos < len(search_text)
                    and search_text[approx_pos - 1].isalpha()
                    and search_text[approx_pos].isalpha()):
                word_tail = re.search(r'[^a-zA-Z]', search_text[approx_pos:])
                if word_tail:
                    approx_pos = approx_pos + word_tail.start()
            # Find nearest sentence-ending punctuation after approx_pos
            sent_end = re.search(r'[.!?;"\u201d]\s', search_text[approx_pos:])
            if sent_end:
                end_pos = approx_pos + sent_end.start() + 1
                return end_pos, end_pos
            # No sentence boundary — find end of current word
            word_end = re.search(r'(?<=[a-zA-Z])\b', search_text[approx_pos:])
            if word_end:
                end_pos = approx_pos + word_end.start()
                return end_pos, end_pos
            # At end of text
            if approx_pos > 0:
                return approx_pos, approx_pos

    return -1, -1


def _reposition_markers(data: Dict[str, Any]) -> Tuple[int, int]:
    """
    Reposition misplaced [N] markers to be adjacent to their footnoted term.

    The LLM sometimes places markers at clause boundaries instead of right
    after the footnoted term. This function finds each footnote's pinyin or
    English term in the text and moves the marker there.

    Footnotes whose term cannot be found in the text are removed entirely —
    a marker next to an unrelated word is worse than no footnote at all.

    Returns (repositioned_count, removed_count).
    """
    repositioned = 0
    removed = 0
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

    for chapter in chapters:
        for block in chapter.get("content_blocks", []):
            footnotes = block.get("footnotes", [])
            text = block.get("translated_content", "")
            if not footnotes or not text:
                continue

            # Strip ALL markers from the text
            clean_text = re.sub(r"\[\d+\]", "", text)

            # Build a position map from naked text (no * markers) back to clean_text.
            # _find_term_in_text strips * internally, so we must search in naked text
            # and then map positions back to clean_text for insertion.
            naked_text = clean_text.replace("*", "")
            # Map: naked_pos -> clean_pos
            naked_to_clean = []
            ci = 0
            for ni in range(len(naked_text)):
                while ci < len(clean_text) and clean_text[ci] == "*":
                    ci += 1
                naked_to_clean.append(ci)
                ci += 1
            # Sentinel for end-of-string positions
            naked_to_clean.append(len(clean_text))

            # Find where each footnote's term appears (in naked text)
            positioned_fns = []  # (naked_end_position, fn)

            source_text = block.get("content", "")

            for fn in footnotes:
                pinyin = fn.get("pinyin", "").strip()
                explanation = fn.get("explanation", "").strip()
                ideogram = fn.get("ideogram", "")

                start, end = _find_term_in_text(
                    clean_text, pinyin, explanation,
                    ideogram=ideogram, source_text=source_text,
                )

                if end != -1:
                    positioned_fns.append((end, fn))
                    repositioned += 1
                else:
                    removed += 1
                    logger.debug(
                        f"Removing unanchored footnote ({ideogram}) "
                        f"from {block.get('id', '?')}: term not found in text"
                    )

            if not positioned_fns:
                block["footnotes"] = []
                continue

            # Sort by text position (left to right) — this determines footnote order
            positioned_fns.sort(key=lambda x: x[0])

            # Assign sequential keys matching text order, then insert markers
            surviving_fns = []
            insertions = []
            # Characters that a marker should be placed AFTER (outside quotes/parens)
            _closing_chars = set("\"'」）)\u201d\u2019")
            for new_key, (naked_pos, fn) in enumerate(positioned_fns, 1):
                fn["key"] = new_key
                surviving_fns.append(fn)
                # Map naked position back to clean_text position
                if naked_pos < len(naked_to_clean):
                    insert_pos = naked_to_clean[naked_pos]
                else:
                    insert_pos = len(clean_text)
                # Advance past closing quotes/punctuation AND asterisks
                while insert_pos < len(clean_text) and clean_text[insert_pos] in _closing_chars or (insert_pos < len(clean_text) and clean_text[insert_pos] == "*"):
                    insert_pos += 1
                insertions.append((insert_pos, f"[{new_key}]"))

            block["footnotes"] = surviving_fns

            # Insert markers in reverse position order so indices stay valid
            insertions.sort(key=lambda x: x[0], reverse=True)
            result = clean_text
            for pos, marker in insertions:
                result = result[:pos] + marker + result[pos:]

            block["translated_content"] = result

    return repositioned, removed


def _sanitize_orphan_markers(data: Dict[str, Any]) -> int:
    """Strip [N] markers from translated text that have no matching footnote."""
    blocks_fixed = 0
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
    for chapter in chapters:
        for block in chapter.get("content_blocks", []):
            text = block.get("translated_content", "")
            if not text:
                continue
            fns = block.get("footnotes", [])
            valid_keys = {str(fn.get("key")) for fn in fns}
            markers = set(re.findall(r"\[(\d+)\]", text))
            orphans = markers - valid_keys
            if orphans:
                def _strip(match, _orphans=orphans):
                    return "" if match.group(1) in _orphans else match.group(0)
                block["translated_content"] = re.sub(r"\[(\d+)\]", _strip, text)
                blocks_fixed += 1
    return blocks_fixed


def _ai_verify_marker_positions(data: Dict[str, Any], client) -> int:
    """
    Use a cheap nano model to verify footnote marker placement.

    For each block with footnotes, sends the translated text + footnote list
    and asks the model to return corrected text with markers placed
    immediately after the term they annotate.

    Only called on surviving footnotes (typically 20-30 per chapter),
    so cost is minimal: one API call per block with footnotes.

    Returns number of blocks where markers were repositioned.
    """
    repositioned = 0
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

    for chapter in chapters:
        for block in chapter.get("content_blocks", []):
            footnotes = block.get("footnotes", [])
            text = block.get("translated_content", "")
            if not footnotes or not text:
                continue

            # Build footnote reference for the model
            fn_list = []
            for fn in footnotes:
                fn_list.append(
                    f"[{fn['key']}] {fn.get('ideogram', '')} "
                    f"({fn.get('pinyin', '')}) — {fn.get('explanation', '')[:60]}"
                )
            fn_ref = "\n".join(fn_list)

            prompt = (
                "Below is an English translation with footnote markers [1], [2], etc. "
                "and a list of what each marker annotates.\n\n"
                "Your task: verify each [N] marker is placed IMMEDIATELY after the "
                "term it annotates. If a marker is misplaced (e.g., at end of "
                "paragraph instead of after the term), move it to the correct "
                "position — right after the annotated term, outside any quotes.\n\n"
                "Rules:\n"
                "- Do NOT change the translation text itself\n"
                "- Do NOT add or remove footnotes\n"
                "- Do NOT change footnote numbering\n"
                "- ONLY move misplaced markers\n"
                "- If a marker is already correctly placed, leave it\n\n"
                f"FOOTNOTES:\n{fn_ref}\n\n"
                f"TEXT:\n{text}\n\n"
                "Return ONLY the corrected text (no explanation, no JSON wrapper)."
            )

            try:
                response = client.chat(LLMRequest(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    timeout=30,
                ))
                corrected = response.text.strip()

                # Sanity check: must have same number of markers
                old_markers = sorted(re.findall(r"\[\d+\]", text))
                new_markers = sorted(re.findall(r"\[\d+\]", corrected))

                if old_markers == new_markers and corrected != text:
                    block["translated_content"] = corrected
                    repositioned += 1
                    logger.debug(
                        f"AI repositioned markers in {block.get('id', '?')}"
                    )
                elif old_markers != new_markers:
                    logger.warning(
                        f"AI verification changed marker count in "
                        f"{block.get('id', '?')}, skipping"
                    )

            except Exception as e:
                logger.warning(f"AI marker verification failed: {e}")
                continue

    return repositioned


def _remap_markers(
    text: str,
    old_to_new: Dict[int, int],
    removed_keys: set,
) -> str:
    """Remap/remove inline footnote markers based on key changes."""

    def replace_marker(match):
        old_key = int(match.group(1))
        if old_key in removed_keys:
            return ""
        new_key = old_to_new.get(old_key)
        if new_key is not None:
            return f"[{new_key}]"
        return match.group(0)

    return re.sub(r"\[(\d+)\]", replace_marker, text)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Remove trivial footnotes using AI-powered triviality scoring"
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Input JSON file path",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON file path (default: trivial_cleaned/{filename})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./trivial_cleaned"),
        help="Output directory (default: ./trivial_cleaned)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Score footnotes without writing output",
    )
    parser.add_argument(
        "--triviality-threshold",
        type=int,
        default=60,
        help="Triviality score threshold for removal (default: 60)",
    )
    parser.add_argument(
        "--cultural-threshold",
        type=int,
        default=40,
        help="Cultural specificity score below which removal is allowed (default: 40)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Batch size for API calls (default: 10)",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        help="Directory for cleanup report (default: same as output)",
    )

    args = parser.parse_args()

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        output_path = args.output_dir / args.input.name

    # Configure
    config = TrivialityConfig(
        triviality_threshold=args.triviality_threshold,
        cultural_threshold=args.cultural_threshold,
        batch_size=args.batch_size,
    )

    # Process
    remover = TrivialFootnoteRemover(config)
    result = remover.process_file(args.input, output_path, dry_run=args.dry_run)

    # Log summary
    summary = result.to_dict()["summary"]
    logger.info("=" * 60)
    logger.info("Triviality Removal Results")
    logger.info("=" * 60)
    for k, v in summary.items():
        logger.info("  %s: %s", k, v)
    logger.info("=" * 60)

    # Save report
    log_dir = args.log_dir or output_path.parent
    log_dir.mkdir(parents=True, exist_ok=True)
    report_path = log_dir / f"{args.input.stem}_triviality_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
    logger.info("Report saved to: %s", report_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
