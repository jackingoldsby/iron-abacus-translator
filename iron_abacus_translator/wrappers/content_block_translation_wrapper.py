#!/usr/bin/env python3
"""
Content Block Translation Wrapper

Wraps the translation infrastructure with:
- System prompts (anti-spoiler, suppress list, density guidance)
- FootnoteContextAccumulator for cross-block deduplication
- Dedup-aware glossary context via build_glossary_context()
- Density diagnostic logging (no auto-trimming)
- Suppress list integration

Usage:
    from wrappers.content_block_translation_wrapper import ContentBlockTranslationWrapper
    from utils.footnote_context import FootnoteContextAccumulator

    accumulator = FootnoteContextAccumulator()
    wrapper = ContentBlockTranslationWrapper(accumulator=accumulator)
    result = wrapper.execute(content_text_id=1, content_source_text="...", work_id="D1379")
"""

import json
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.clients import get_llm_client, LLMRequest

from utils.footnote_context import FootnoteContextAccumulator
from utils.glossary_context_builder import build_glossary_context
from utils.glossary import TranslationGlossary, GlossaryEntry
from processors.translation_prompts import (
    build_system_prompt,
    get_suppress_ideograms,
)
from processors.translator import (
    TranslationResponse,
    TranslatedAnnotatedContent,
    ContentFootnote,
    FootnoteDetails,
)

logger = logging.getLogger(__name__)


@dataclass
class TranslationResult:
    """Result from content block translation."""
    success: bool
    translated_data: Optional[Dict[str, Any]] = None
    footnote_count: int = 0
    density_diagnostic: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    attempts_used: int = 1


# Alias for backward compatibility
ContentBlockTranslationResult = TranslationResult


class ContentBlockTranslationWrapper:
    """
    Translation wrapper with accumulator dedup and suppress list.

    Features:
    - System prompt with suppress list, no character name footnotes,
      no spoilers, relaxed density
    - FootnoteContextAccumulator for cross-block dedup
    - Dedup-aware glossary context
    - Logs density diagnostic (does not auto-trim)
    - Registers surviving ideograms in accumulator after translation
    """

    def __init__(
        self,
        accumulator: Optional[FootnoteContextAccumulator] = None,
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_retries: int = 3,
        timeout: int = 120,
        glossary_path: Optional[Path] = None,
        suppress_list_path: Optional[Path] = None,
        llm_client=None,
        target_lang: str = "en",
    ):
        """Initialize the content-block translation wrapper.

        Args:
            accumulator: Cross-block footnote dedup tracker. Created if None.
            model: LLM model identifier; resolved by factory if omitted.
            temperature: Sampling temperature for translation calls.
            max_retries: Max retry attempts per LLM call.
            timeout: Per-call timeout in seconds.
            glossary_path: Optional path to a glossary JSON file.
            suppress_list_path: Path to wuxia suppress-list JSON
                (ideograms that should never get footnotes).
            llm_client: Pre-built LLM client; created via factory if None.
            target_lang: ISO 639-1 target language code (default "en").
        """
        self.accumulator = accumulator or FootnoteContextAccumulator()
        self.temperature = temperature
        self.max_retries = max_retries
        self.timeout = timeout
        self.suppress_list_path = suppress_list_path
        self.target_lang = target_lang
        self._suppress_ideograms = get_suppress_ideograms(suppress_list_path)

        # Initialize LLM client — model resolved by factory if not explicit
        self.llm = llm_client or get_llm_client(component="translator", model=model)
        self.model = self.llm.model
        self.provider = getattr(self.llm, 'provider', None)

        # Initialize glossary
        if glossary_path is None:
            glossary_path = Path(__file__).parent.parent / "glossary.db"
        try:
            self.glossary = TranslationGlossary(glossary_path)
        except FileNotFoundError:
            logger.warning(f"Glossary not found at {glossary_path}")
            self.glossary = None

        # Build base system prompt (with suppress list + provider-specific rules)
        self._base_system_prompt = build_system_prompt(
            suppress_list_path=suppress_list_path,
            provider=self.provider,
            target_lang=self.target_lang,
        )

        logger.info(
            f"Initialized wrapper: model={model}, provider={self.provider}, "
            f"target_lang={self.target_lang}, "
            f"suppress_list={len(self._suppress_ideograms)} terms, "
            f"accumulator={self.accumulator}"
        )

    def execute(
        self,
        content_text_id: int,
        content_source_text: str,
        work_id: Optional[str] = None,
        chapter_num: Optional[int] = None,
    ) -> TranslationResult:
        """
        Translate a content block.

        Args:
            content_text_id: Unique ID for this content block
            content_source_text: Chinese source text
            work_id: Work ID for tracking
            chapter_num: Chapter number (for accumulator registration)

        Returns:
            TranslationResult
        """
        if not content_source_text or len(content_source_text.strip()) < 5:
            return TranslationResult(
                success=False, error="Source text too short"
            )

        # Scan for glossary terms
        glossary_matches = self._scan_glossary(content_source_text)

        # Build dedup-aware glossary context
        glossary_context = ""
        if glossary_matches:
            glossary_context = build_glossary_context(
                glossary_matches, self.accumulator
            )

        # Build already-footnoted context for prompt
        already_context = self._build_already_footnoted_context()

        # Build complete system prompt (with provider-specific rules)
        system_prompt = build_system_prompt(
            suppress_list_path=self.suppress_list_path,
            already_footnoted_context=already_context,
            provider=self.provider,
            target_lang=self.target_lang,
        )

        # Build user message
        user_message = json.dumps({
            "content_text_id": content_text_id,
            "content_source_text": content_source_text,
        }, ensure_ascii=False)

        if glossary_context:
            user_message += glossary_context

        # Retry loop
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._call_api(system_prompt, user_message)
                parsed = self._parse_response(response)

                # Filter out suppressed and already-footnoted terms
                original_count = len(parsed["footnotes"])
                filtered_footnotes = self._filter_footnotes(
                    parsed["footnotes"], chapter_num
                )
                parsed["footnotes"] = filtered_footnotes

                # Ensure markers in text match surviving footnotes
                parsed["translated_text"] = self._ensure_markers(
                    parsed["translated_text"], filtered_footnotes,
                    source_text=content_source_text,
                )

                # Register surviving ideograms in accumulator
                ch = chapter_num or 0
                surviving_ideograms = [
                    fn.get("ideogram", "") for fn in filtered_footnotes
                    if fn.get("ideogram")
                ]
                self.accumulator.register(surviving_ideograms, ch)

                return TranslationResult(
                    success=True,
                    translated_data={
                        "content_text_id": content_text_id,
                        "content_source_text": content_source_text,
                        "translated_annotated_content": {
                            "annotated_content_text": parsed["translated_text"],
                            "content_footnotes": [
                                {
                                    "footnote_key": fn["key"],
                                    "footnote_details": {
                                        "footnote_ideogram": fn.get("ideogram", ""),
                                        "footnote_pinyin": fn.get("pinyin", ""),
                                        "footnote_explanation": fn.get("explanation", ""),
                                    },
                                }
                                for fn in filtered_footnotes
                            ],
                            "content_type": parsed.get("content_type", "narrative"),
                        },
                    },
                    footnote_count=len(filtered_footnotes),
                    density_diagnostic=None,
                    attempts_used=attempt,
                )

            except Exception as e:
                logger.error(f"Attempt {attempt}/{self.max_retries} failed: {e}")
                if attempt < self.max_retries:
                    time.sleep(2)
                    continue
                return TranslationResult(
                    success=False,
                    error=f"Failed after {self.max_retries} attempts: {e}",
                    attempts_used=attempt,
                )

    def _call_api(self, system_prompt: str, user_message: str) -> str:
        """Call LLM with translation prompt."""
        response = self.llm.chat(LLMRequest(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            model=self.model,
            temperature=self.temperature,
            json_mode=True,
            timeout=self.timeout,
        ))
        return response.text

    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse the JSON response from the API."""
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            # Try fixing common issues
            fixed = re.sub(r',(\s*[\]}])', r'\1', response_text)
            data = json.loads(fixed)

        annotated = data.get("translated_annotated_content", {})
        raw_footnotes = annotated.get("content_footnotes", [])

        footnotes = []
        for fn in raw_footnotes:
            details = fn.get("footnote_details", {})
            footnotes.append({
                "key": fn.get("footnote_key", 0),
                "ideogram": details.get("footnote_ideogram", ""),
                "pinyin": details.get("footnote_pinyin", ""),
                "explanation": details.get("footnote_explanation", ""),
            })

        return {
            "translated_text": annotated.get("annotated_content_text", ""),
            "footnotes": footnotes,
            "content_type": annotated.get("content_type", "narrative"),
        }

    def _filter_footnotes(
        self,
        footnotes: List[Dict[str, Any]],
        chapter_num: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Filter out suppressed and already-footnoted terms.

        Returns filtered list with sequential keys.
        """
        filtered = []
        for fn in footnotes:
            ideogram = fn.get("ideogram", "")
            explanation = fn.get("explanation", "")

            # Skip empty/ghost footnotes (model emitted key but no content)
            if not ideogram or not explanation:
                logger.debug(f"Skipped empty footnote: key={fn.get('key')}")
                continue

            # Skip suppressed terms
            if ideogram in self._suppress_ideograms:
                logger.debug(f"Suppressed: {ideogram}")
                continue

            # Skip already-footnoted terms (dedup)
            if self.accumulator.is_already_footnoted(ideogram):
                logger.debug(f"Dedup suppressed: {ideogram}")
                continue

            # Validate and correct pinyin against ground truth
            fn["pinyin"] = self._validate_pinyin(ideogram, fn.get("pinyin", ""))

            filtered.append(fn)

        # Renumber keys sequentially
        for i, fn in enumerate(filtered, start=1):
            fn["key"] = i

        return filtered

    @staticmethod
    def _validate_pinyin(ideogram: str, model_pinyin: str) -> str:
        """Validate model-generated pinyin against pypinyin ground truth.

        Preserves the model's spacing/capitalization style but corrects
        wrong syllables using character-by-character lookup.
        """
        try:
            from pypinyin import pinyin, Style
        except ImportError:
            return model_pinyin

        if not ideogram or not model_pinyin:
            return model_pinyin

        # Get ground-truth pinyin per character
        correct_syllables = [p[0] for p in pinyin(ideogram, style=Style.TONE)]

        # Strip model pinyin to bare syllables for comparison
        model_stripped = model_pinyin.lower().replace(" ", "").replace("'", "")
        correct_stripped = "".join(correct_syllables).lower()

        if model_stripped == correct_stripped:
            return model_pinyin  # Already correct, keep original formatting

        # Reconstruct: use correct syllables, preserve model capitalization
        was_capitalized = model_pinyin[0].isupper() if model_pinyin else False
        corrected = " ".join(correct_syllables)

        # Preserve title-case if model had it
        if was_capitalized:
            # Capitalize first letter of each word that was capitalized in original
            model_words = model_pinyin.split()
            correct_words = corrected.split()
            result = []
            for i, cw in enumerate(correct_words):
                if i < len(model_words) and model_words[i][0].isupper():
                    result.append(cw[0].upper() + cw[1:])
                else:
                    result.append(cw)
            corrected = " ".join(result)

        if corrected.lower().replace(" ", "") != model_stripped:
            logger.debug(f"Pinyin corrected: {ideogram}: {model_pinyin} → {corrected}")

        return corrected

    def _ensure_markers(
        self,
        text: str,
        footnotes: List[Dict[str, Any]],
        source_text: str = "",
    ) -> str:
        """Ensure every surviving footnote has a [N] marker in the text.

        Strategy:
        1. Strip all existing markers to start clean.
        2. For each footnote, try multiple search strategies to find where
           the term appears in the text.
        3. Place marker right after the matched term.
        4. If not found, use source-text positional mapping as fallback.
        5. Last resort: append at end of text.
        """
        # Strip all old markers
        clean = re.sub(r'\[\d+\]', '', text)

        for fn in footnotes:
            key = fn["key"]
            marker = f"[{key}]"
            pinyin = fn.get("pinyin", "").strip()
            explanation = fn.get("explanation", "")
            ideogram = fn.get("ideogram", "")

            idx, match_len = self._find_term_in_text(clean, pinyin, explanation)

            if idx == -1 and ideogram and source_text:
                # Positional fallback: find ideogram in source, map to
                # proportional position in translated text, then find
                # the nearest sentence boundary.
                src_idx = source_text.find(ideogram)
                if src_idx != -1:
                    ratio = (src_idx + len(ideogram)) / max(len(source_text), 1)
                    # Strip existing markers before computing position to
                    # avoid drift from previously inserted markers.
                    clean_no_markers = re.sub(r'\[\d+\]', '', clean)
                    raw_pos = int(ratio * len(clean_no_markers))
                    # Map raw_pos back to position in clean (which has markers)
                    chars_seen = 0
                    approx_pos = 0
                    i = 0
                    while i < len(clean) and chars_seen < raw_pos:
                        # Skip over marker sequences like [12]
                        m_skip = re.match(r'\[\d+\]', clean[i:])
                        if m_skip:
                            i += m_skip.end()
                            continue
                        chars_seen += 1
                        i += 1
                    approx_pos = i
                    # Snap to word boundary: back up if we're mid-word
                    if approx_pos < len(clean) and approx_pos > 0:
                        if clean[approx_pos - 1].isalpha() and (
                            approx_pos < len(clean) and clean[approx_pos].isalpha()
                        ):
                            # Mid-word — find end of current word
                            word_tail = re.search(r'[^a-zA-Z]', clean[approx_pos:])
                            if word_tail:
                                approx_pos = approx_pos + word_tail.start()
                    # Find nearest sentence-ending punctuation after approx_pos
                    sent_end = re.search(
                        r'[.!?;"\u201d]\s', clean[approx_pos:]
                    )
                    if sent_end:
                        idx = approx_pos + sent_end.start() + 1
                        match_len = 0
                    else:
                        # No sentence boundary — find end of current word
                        word_end = re.search(r'(?<=[a-zA-Z])\b', clean[approx_pos:])
                        if word_end:
                            idx = approx_pos + word_end.start()
                            match_len = 0
                        elif approx_pos > 0:
                            # At end of text — just use approx_pos
                            idx = approx_pos
                            match_len = 0

            if idx != -1:
                insert_pos = idx + match_len
                # Snap to word boundary if we landed mid-word
                if (insert_pos < len(clean) and insert_pos > 0
                        and clean[insert_pos - 1].isalpha()
                        and clean[insert_pos].isalpha()):
                    word_tail = re.search(r'[^a-zA-ZÀ-ÿ\u0300-\u036f]', clean[insert_pos:])
                    if word_tail:
                        insert_pos = insert_pos + word_tail.start()
                    else:
                        insert_pos = len(clean)  # end of text
                clean = clean[:insert_pos] + marker + clean[insert_pos:]
            else:
                # Last resort: append at end
                clean = clean.rstrip() + marker + " "

        return clean.strip()

    @staticmethod
    def _strip_tones(text: str) -> str:
        """Remove combining diacritical marks (tone marks) from text."""
        return ''.join(
            c for c in unicodedata.normalize('NFD', text)
            if unicodedata.category(c) != 'Mn'
        )

    def _find_term_in_text(
        self, text: str, pinyin: str, explanation: str = ""
    ) -> Tuple[int, int]:
        """Find where a footnoted term appears in translated text.

        Tries pinyin-based strategies first, then explanation-based fallbacks:
        1. Exact full pinyin match (e.g., "Wǔdāng Shān")
        2. Full pinyin without tone marks (e.g., "Wudang Shan")
        3. First word of multi-word pinyin with tones (e.g., "Wǔdāng")
        4. First word without tones (e.g., "Wudang")
        5. Joined form without spaces (e.g., "Jǐnyīwèi" for "jǐn yī wèi")
        6. Quoted terms from explanation (e.g., 'Embroidered Uniform Guard')
        7. "translated as X" / "known as X" patterns
        8. Hyphenated capitalized terms (e.g., Governor-General)
        9. Multi-word capitalized terms from explanation

        Returns (index, match_length) or (-1, 0) if not found.
        """
        if pinyin:
            pinyin_base = self._strip_tones(pinyin)
            text_base = self._strip_tones(text).lower()
            words = pinyin.split()

            # Strategy 1: exact full match (with tones)
            idx = text.find(pinyin)
            if idx != -1:
                return idx, len(pinyin)

            # Strategy 2: full match without tones
            idx = text_base.find(pinyin_base.lower())
            if idx != -1:
                return idx, len(pinyin_base)

            if len(words) > 1:
                # Strategy 3: first word with tones
                first = words[0]
                idx = text.find(first)
                if idx != -1:
                    # Extend match to include following words if present
                    end = idx + len(first)
                    for w in words[1:]:
                        lookahead = text[end:end + len(w) + 3]
                        w_pos = lookahead.find(w)
                        if w_pos != -1:
                            end = end + w_pos + len(w)
                        else:
                            break
                    return idx, end - idx

                # Strategy 4: first word without tones
                first_base = self._strip_tones(first)
                idx = text_base.find(first_base.lower())
                if idx != -1:
                    return idx, len(first_base)

            # Strategy 5: joined form (e.g., "Jǐnyīwèi")
            joined = pinyin.replace(" ", "")
            idx = text.find(joined)
            if idx != -1:
                return idx, len(joined)
            joined_base = self._strip_tones(joined)
            idx = text_base.find(joined_base.lower())
            if idx != -1:
                return idx, len(joined_base)

        # Explanation-based strategies
        if explanation:
            # Strategy 6: quoted terms
            for q in re.findall(r"'([^']+)'", explanation):
                idx = text.find(q)
                if idx != -1:
                    return idx, len(q)

            # Strategy 7: "translated as X" / "known as X"
            for m in re.finditer(
                r"(?:translated as|known as|called) "
                r"([A-Z][\w-]+(?:\s+[A-Z]?[\w-]+)*)",
                explanation,
            ):
                term = m.group(1)
                idx = text.find(term)
                if idx != -1:
                    return idx, len(term)

            # Strategy 8: hyphenated capitalized terms (e.g., Governor-General)
            for m in re.finditer(r"[A-Z][a-z]+(?:-[A-Z]?[a-z]+)+", explanation):
                term = m.group()
                if len(term) > 4:
                    idx = text.find(term)
                    if idx != -1:
                        return idx, len(term)

            # Strategy 9: multi-word capitalized terms
            for m in re.finditer(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+", explanation):
                term = m.group()
                if len(term) > 6:
                    idx = text.find(term)
                    if idx != -1:
                        return idx, len(term)

        # Strategy 10: positional — find ideogram in source text, map to
        # approximate position in translated text.  This handles cases where
        # the model translated the term to English inline (e.g., 鐵砂掌 →
        # "Iron Sand Palm") and neither pinyin nor explanation keywords match.
        # Implemented in the caller via source_text parameter if provided.

        return -1, 0

    def _build_already_footnoted_context(self) -> str:
        """Build context string listing already-footnoted terms."""
        total = self.accumulator.total_registered
        if total == 0:
            return ""

        # Get a sample of already-footnoted terms (don't overwhelm the prompt)
        all_terms = sorted(self.accumulator.all_footnoted_ideograms)

        if len(all_terms) <= 30:
            sample = all_terms
        else:
            sample = all_terms[:30]

        lines = [
            "\n**ALREADY FOOTNOTED (do NOT re-footnote these terms):**",
            f"({total} terms total, showing first {len(sample)})",
        ]
        lines.append(", ".join(sample))

        return "\n".join(lines)

    def _scan_glossary(
        self, text: str
    ) -> List[Tuple[str, GlossaryEntry, int]]:
        """Scan source text for glossary terms."""
        if not self.glossary:
            return []
        return self.glossary.find_in_text(text, max_matches=30)
