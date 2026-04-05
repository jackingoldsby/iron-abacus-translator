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

- `formula_pinyin` — A martial formula, combat couplet, training mnemonic, or rhyming martial instruction (口訣) left as pinyin instead of translated to English. These must be rendered as English so the reader understands the combat instruction or poetic meaning. The pinyin belongs in a footnote, not in the body text.

- `char_count` — The text references a count of Chinese characters or words (e.g. "thirteen characters," "seven words") without a footnote giving the original ideograms and breakdown. The count is meaningless to an English reader without seeing the Chinese.

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


# =====================================================================
# Programmatic detection helpers (no LLM needed)
# =====================================================================

def _find_cjk_in_translation(text: str) -> List[str]:
    """Find CJK ideograms in translated text. Returns list of found ideogram runs."""
    if not text:
        return []
    cjk_pattern = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+')
    return cjk_pattern.findall(text)


# --- char_count: "N characters/words" references ---

# Only match explicit numeric counts: "thirteen characters", "7 words"
# Number words that indicate a specific count of Chinese text
_NUMBER_WORDS = (
    "one|two|three|four|five|six|seven|eight|nine|ten|"
    "eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    "thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
    r"twenty[- ]\w+|thirty[- ]\w+|forty[- ]\w+|fifty[- ]\w+"
)
_CHAR_COUNT_RE = re.compile(
    r'\b(' + _NUMBER_WORDS + r')\s+'
    r'(characters?|ideograms?)\b',
    re.IGNORECASE,
)
_CHAR_COUNT_DIGIT_RE = re.compile(
    r'\b(\d+)\s+'
    r'(characters?|ideograms?)\b',
    re.IGNORECASE,
)


def _has_character_count_ref(text: str, footnotes: list) -> bool:
    """Detect 'N characters/words' with no footnote marker nearby."""
    if not text:
        return False
    for pattern in (_CHAR_COUNT_RE, _CHAR_COUNT_DIGIT_RE):
        for m in pattern.finditer(text):
            after = text[m.end():m.end() + 30]
            if not re.search(r'\[\d+\]', after):
                before = text[max(0, m.start() - 10):m.start()]
                if not re.search(r'\[\d+\]', before):
                    return True
    return False


# --- long_sword: "long sword(s)" in body text ---

_LONG_SWORD_RE = re.compile(r'\blong\s+swords?\b', re.IGNORECASE)


def _has_long_sword(text: str) -> bool:
    """Detect 'long sword' or 'long swords' in body text."""
    return bool(text and _LONG_SWORD_RE.search(text))


# --- bare_pinyin: common honorific/term pinyin without tone marks ---

# Map of bare pinyin → expected tone-marked form
_BARE_PINYIN_TERMS = {
    "Shifu": "Shīfù", "shifu": "shīfù",
    "Shixiong": "Shīxiōng", "shixiong": "shīxiōng",
    "Shijie": "Shījiě", "shijie": "shījiě",
    "Shimei": "Shīmèi", "shimei": "shīmèi",
    "Shidi": "Shīdì", "shidi": "shīdì",
    "Shige": "Shīgē", "shige": "shīgē",
    "Guniang": "Gūniáng", "guniang": "gūniáng",
    "Bangzhu": "Bāngzhǔ", "bangzhu": "bāngzhǔ",
    "Zhangmen": "Zhǎngmén", "zhangmen": "zhǎngmén",
    "Zhuangzhu": "Zhuāngzhǔ", "zhuangzhu": "zhuāngzhǔ",
    "Dashi": "Dàshī", "dashi": "dàshī",
    "Fangzhang": "Fāngzhàng", "fangzhang": "fāngzhàng",
    "Qianbei": "Qiánbèi", "qianbei": "qiánbèi",
    "Wanbei": "Wǎnbèi", "wanbei": "wǎnbèi",
    "Dage": "Dàgē", "dage": "dàgē",
    "Gongzi": "Gōngzǐ", "gongzi": "gōngzǐ",
    "Xianggong": "Xiànggong", "xianggong": "xiànggong",
    "Laoye": "Lǎoyé", "laoye": "lǎoyé",
    "Jianghu": "Jiānghú", "jianghu": "jiānghú",
    "Wulin": "Wǔlín", "wulin": "wǔlín",
    "Qinggong": "Qīnggōng", "qinggong": "qīnggōng",
    "Neigong": "Nèigōng", "neigong": "nèigōng",
    "Dianxue": "Diǎnxué", "dianxue": "diǎnxué",
    "Qinna": "Qínná", "qinna": "qínná",
    "Taiji": "Tàijí", "taiji": "tàijí",
}

# Build regex: word-boundary match for each bare term
_BARE_PINYIN_RE = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in _BARE_PINYIN_TERMS) + r')\b'
)


def _has_bare_pinyin(text: str) -> bool:
    """Detect common pinyin terms without tone diacritics."""
    if not text:
        return False
    for m in _BARE_PINYIN_RE.finditer(text):
        # Make sure it's not inside an italic span (already being flagged differently)
        start = max(0, m.start() - 1)
        if text[start] != '*':
            return True
    return False


# --- pinyin_sequence: repeated pinyin syllables not italicized ---
# Catches: "sou sou sou", "peng peng peng", "dang dang dang"
# Should be: "*sōu sōu sōu*", "*pēng pēng pēng*"

_PINYIN_SEQUENCE_RE = re.compile(
    r'(?<!\*)\b([A-ZÀ-ÖØ-öø-ÿa-z]{1,6})\s+\1(?:\s+\1)*\b(?!\*)',
    re.IGNORECASE,
)


def _has_unitalicized_pinyin_sequence(text: str) -> bool:
    """Detect repeated pinyin syllables not wrapped in *asterisks*."""
    if not text:
        return False
    for m in _PINYIN_SEQUENCE_RE.finditer(text):
        word = m.group(1).lower()
        # Filter out common English repeated words
        if word in ("the", "and", "but", "for", "not", "all", "had", "was",
                     "his", "her", "him", "she", "they", "very", "more",
                     "that", "this", "with", "have", "been", "were", "will",
                     "one", "two", "did", "too", "over", "just", "than",
                     "now", "even", "much", "most", "each", "long", "back"):
            continue
        return True
    return False


# --- suppressed_footnote: footnote ideogram on suppress list ---

_suppress_set: Optional[Set[str]] = None


def _get_suppress_set() -> Set[str]:
    """Lazy-load the suppress list."""
    global _suppress_set
    if _suppress_set is None:
        try:
            from processors.translation_prompts import get_suppress_ideograms
            _suppress_set = get_suppress_ideograms()
        except Exception:
            _suppress_set = set()
    return _suppress_set


def _has_suppressed_footnote(footnotes: list) -> bool:
    """Check if any footnote's ideogram is on the suppress list."""
    if not footnotes:
        return False
    suppressed = _get_suppress_set()
    if not suppressed:
        return False
    for fn in footnotes:
        ideogram = fn.get("ideogram", "")
        if ideogram and ideogram in suppressed:
            return True
    return False


# --- omission: translated text suspiciously short vs source ---

def _is_omission(source: str, translated: str) -> bool:
    """Detect blocks where translated content is suspiciously short vs source.

    Chinese is ~2-4x denser than English, so English should typically be
    longer than the Chinese. If English is shorter than the Chinese source
    for blocks >50 chars, something was likely omitted.
    """
    if not source or not translated:
        return False
    if len(source) < 50:
        return False
    # English should be at minimum roughly the same length as Chinese
    # (usually 1.5-4x longer). If it's less than 80% of Chinese length,
    # content was likely dropped.
    return len(translated) < len(source) * 0.8


# --- duplicate_text: repeated phrases within a block ---

def _has_duplicate_text(text: str) -> bool:
    """Detect repeated phrases >40 chars within a block (LLM stutter)."""
    if not text or len(text) < 100:
        return False
    # Check for any substring of 40+ chars that appears more than once
    min_len = 40
    for i in range(len(text) - min_len * 2):
        chunk = text[i:i + min_len]
        if text.find(chunk, i + min_len) != -1:
            return True
    return False


# --- unitalicized_honorific: honorific pinyin with tones but no asterisks ---

_HONORIFIC_PINYIN_WITH_TONES = [
    "Shīfù", "Shīxiōng", "Shījiě", "Shīmèi", "Shīdì", "Shīgē",
    "Gūniáng", "Bāngzhǔ", "Zhǎngmén", "Zhuāngzhǔ", "Dàshī",
    "Fāngzhàng", "Qiánbèi", "Wǎnbèi", "Dàgē", "Gōngzǐ",
    "Xiànggong", "Lǎoyé", "Gōnggōng", "Niángzǐ",
]

_UNITAL_HONORIFIC_RE = re.compile(
    r'(?<!\*)(' + '|'.join(re.escape(h) for h in _HONORIFIC_PINYIN_WITH_TONES) + r')(?!\*)',
)


def _has_unitalicized_honorific(text: str) -> bool:
    """Detect honorific pinyin with tone marks but not wrapped in *asterisks*."""
    if not text:
        return False
    return bool(_UNITAL_HONORIFIC_RE.search(text))


# --- orphan_marker: [N] in text with no footnote, or footnote with no marker ---

def _has_orphan_marker(text: str, footnotes: list) -> bool:
    """Detect mismatched markers and footnotes."""
    if not text:
        return False
    marker_keys = set(int(m) for m in re.findall(r'\[(\d+)\]', text))
    fn_keys = set(fn.get("key", 0) for fn in (footnotes or []))

    # Markers with no footnote entry
    if marker_keys - fn_keys:
        return True
    # Footnote entries with no marker in text
    if fn_keys - marker_keys:
        return True
    return False


# --- western_units: feet/inches/pounds/miles/yards in body text ---

_WESTERN_UNIT_RE = re.compile(
    r'\b((?:(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|'
    r'eleven|twelve|fifteen|twenty|thirty|forty|fifty|hundred|'
    r'a few|several|some|half a|quarter)\s+)?'
    r'(?:feet|foot|inches?|pounds?|miles?|yards?|ounces?))\b',
    re.IGNORECASE,
)

# Exclude false positives: "feet" in non-measurement context
_FEET_FALSE_POS = re.compile(
    r'\b(at\s+(?:his|her|their|the)\s+feet'
    r'|to\s+(?:his|her|their)\s+feet'
    r'|on\s+(?:his|her|their)\s+feet'
    r'|jumped\s+to\s+(?:his|her)\s+feet'
    r'|rose\s+to\s+(?:his|her)\s+feet'
    r'|leapt?\s+to\s+(?:his|her)\s+feet'
    r'|staggered\s+to\s+(?:his|her)\s+feet'
    r'|scrambled\s+to\s+(?:his|her)\s+feet'
    r'|struggled\s+to\s+(?:his|her)\s+feet'
    r'|stamped\s+(?:his|her)\s+feet?'
    r'|under\s+(?:his|her|their)\s+feet'
    r'|beneath\s+(?:his|her|their)\s+feet'
    r'|swept\s+off\s+(?:his|her)\s+feet'
    r'|back\s+on\s+(?:his|her)\s+feet)\b',
    re.IGNORECASE,
)


def _has_western_units(text: str) -> bool:
    """Detect Western measurement units that should be Chinese units."""
    if not text:
        return False
    for m in _WESTERN_UNIT_RE.finditer(text):
        match_str = m.group()
        # Skip idiomatic "feet" (not a measurement)
        if "feet" in match_str.lower() or "foot" in match_str.lower():
            # Check if this is part of a false-positive idiom
            context_start = max(0, m.start() - 30)
            context = text[context_start:m.end()]
            if _FEET_FALSE_POS.search(context):
                continue
            # Also skip bare "feet" without a number (likely idiomatic)
            if match_str.lower() in ("feet", "foot"):
                continue
        return True
    return False


# --- gang_not_clan: "Gang" used for 幫 organizations ---

_GANG_RE = re.compile(
    r'\b\w+\s+Gang\b'  # "Beggar Gang", "Red Flower Gang" etc.
)


def _has_gang_not_clan(text: str) -> bool:
    """Detect 'X Gang' which should be 'X Clan' for 幫 organizations."""
    if not text:
        return False
    return bool(_GANG_RE.search(text))


# --- empty_footnote: footnote with blank or trivially short explanation ---

def _has_empty_footnote(footnotes: list) -> bool:
    """Detect footnotes with empty or trivially short explanations."""
    if not footnotes:
        return False
    for fn in footnotes:
        explanation = (fn.get("explanation") or "").strip()
        if not explanation or len(explanation) < 10:
            return True
    return False


# --- double_space: leftover from marker removal ---

_DOUBLE_SPACE_RE = re.compile(r'  +')


def _has_double_space(text: str) -> bool:
    """Detect double spaces in body text."""
    return bool(text and _DOUBLE_SPACE_RE.search(text))


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

        # Programmatic pre-pass: detect issues without LLM
        # Programmatic checks — each maps tag name → detector function
        # Detectors receive (translated_content, source_content, footnotes)
        # and return bool. Some only use a subset of args.
        def _tag(block, tag, detector):
            """Apply a programmatic tag if detector fires."""
            existing = block.setdefault("_prog_tags", [])
            if tag not in existing and detector():
                existing.append(tag)
                return True
            return False

        prog_counts: Dict[str, int] = {}
        for block in tasks:
            tc = block.get("translated_content", "")
            src = block.get("content", "")
            fns = block.get("footnotes", [])

            checks = [
                ("ideogram_leak",         lambda: _find_cjk_in_translation(tc)),
                ("char_count",            lambda: _has_character_count_ref(tc, fns)),
                ("weapon",                lambda: _has_long_sword(tc)),
                ("bare_pinyin",           lambda: _has_bare_pinyin(tc)),
                ("pinyin_sequence",       lambda: _has_unitalicized_pinyin_sequence(tc)),
                ("unitalicized_honorific", lambda: _has_unitalicized_honorific(tc)),
                ("suppressed_footnote",   lambda: _has_suppressed_footnote(fns)),
                ("omission",              lambda: _is_omission(src, tc)),
                ("duplicate_text",        lambda: _has_duplicate_text(tc)),
                ("orphan_marker",         lambda: _has_orphan_marker(tc, fns)),
                ("western_units",         lambda: _has_western_units(tc)),
                ("gang_not_clan",         lambda: _has_gang_not_clan(tc)),
                ("empty_footnote",        lambda: _has_empty_footnote(fns)),
                ("double_space",          lambda: _has_double_space(tc)),
            ]

            for tag, detector in checks:
                if _tag(block, tag, detector):
                    prog_counts[tag] = prog_counts.get(tag, 0) + 1

        # Merge programmatic tags into _correction_tags
        for block in tasks:
            prog_tags = block.pop("_prog_tags", [])
            if prog_tags:
                existing = list(block.get("_correction_tags", []) or [])
                for t in prog_tags:
                    if t not in existing:
                        existing.append(t)
                block["_correction_tags"] = existing

        # Log summary
        if prog_counts:
            summary = ", ".join(f"{k}={v}" for k, v in sorted(prog_counts.items()))
            logger.info(f"  Programmatic pre-pass: {summary}")

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
                    # Merge with any programmatic pre-pass tags
                    pre_tags = block.get("_correction_tags", [])
                    if pre_tags and pre_tags != ["clean"]:
                        merged = list(set(pre_tags + [t for t in tags if t != "clean"]))
                        tags = merged if merged else ["clean"]
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
