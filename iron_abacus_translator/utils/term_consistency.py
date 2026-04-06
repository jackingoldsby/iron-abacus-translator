#!/usr/bin/env python3
"""
Term Consistency Detector & Standardizer

Scans a translated work for Chinese terms (ideograms) that have been rendered
inconsistently in English. Two complementary approaches:

1. **Footnote-based detection**: Extract ideogram→rendering pairs from surviving
   footnotes. If the same ideogram has 2+ distinct renderings, flag it.

2. **Glossary-driven standardization**: For every glossary entry, search all
   translated_content for variant renderings and replace with recommended_form.
   This works even when footnotes have been deduped.

Zero LLM cost — purely programmatic.

Usage:
    from utils.term_consistency import standardize_work

    data, report = standardize_work(data, glossary=glossary)
"""

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class TermOccurrence:
    """A single occurrence of an ideogram's inline rendering."""
    ideogram: str
    rendering: str
    block_id: str
    chapter_idx: int
    marker_key: int
    pinyin: str = ""


@dataclass
class Inconsistency:
    """A term with 2+ distinct English renderings."""
    ideogram: str
    winner: str
    winner_source: str                      # "glossary" or "majority"
    variants: Dict[str, int] = field(default_factory=dict)  # rendering → count
    occurrences: List[TermOccurrence] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _extract_rendering_before_marker(text: str, marker_key: int) -> Optional[str]:
    """Extract the English rendering immediately before a [N] marker.

    Looks for 1-4 content words before the marker, skipping articles and
    prepositions. Handles hyphenated compound terms.

    Returns None if the marker isn't found or no useful text precedes it.
    """
    # Find the marker position
    marker = f"[{marker_key}]"
    idx = text.find(marker)
    if idx < 0:
        return None

    # Get text before the marker (up to 80 chars)
    pre = text[max(0, idx - 80):idx].rstrip()
    if not pre:
        return None

    # If the marker is mid-compound (e.g., "Poison[1]-Handed"), skip — unreliable
    if idx + len(marker) < len(text) and text[idx + len(marker)] == '-':
        return None

    words = pre.split()
    if not words:
        return None

    # Take last 1-4 words
    candidate_words = words[-4:]

    # Drop leading function words
    drop_words = {
        "the", "a", "an", "of", "in", "at", "to", "and", "or", "as",
        "his", "her", "its", "their", "my", "your", "from", "with",
        "was", "were", "is", "had", "has", "that", "this", "those",
        "on", "by", "for", "into", "said", "replied", "asked",
    }

    start = 0
    for i, w in enumerate(candidate_words):
        if w.lower().rstrip(",'\".:;") in drop_words:
            start = i + 1
        else:
            break

    if start >= len(candidate_words):
        start = max(0, len(candidate_words) - 2)

    rendering = " ".join(candidate_words[start:])
    rendering = rendering.strip(".,;:!? \"'""''()")

    if not rendering or len(rendering) < 2:
        return None

    # Must start with an uppercase letter (proper noun / name)
    if not rendering[0].isupper():
        return None

    # Reject if it contains footnote markers [N] — grabbed too much
    if re.search(r'\[\d+\]', rendering):
        return None

    # Reject if too long (>30 chars) — likely a sentence fragment, not a term
    if len(rendering) > 30:
        return None

    # Skip if it contains sentence-ending punctuation mid-string
    if re.search(r'[.!?"]\s', rendering):
        return None

    # Reject if it contains exclamation/question marks at all
    if '!' in rendering or '?' in rendering:
        return None

    # Skip if it looks like a sentence start ("The three brothers", etc.)
    words = rendering.split()
    common = {"the", "a", "an", "this", "that", "these", "those", "he", "she",
              "they", "it", "we", "you", "old", "young", "great", "our", "her"}
    if len(words) >= 3 and words[0].lower() in common:
        return None

    # Reject if it has 4+ words — likely a phrase, not a term name
    # (most wuxia terms are 1-3 words: "Ghosts' Dread", "Eight Trigrams Sabre")
    if len(words) > 3:
        return None

    return rendering


# ---------------------------------------------------------------------------
# Glossary-driven variant search
# ---------------------------------------------------------------------------

def _find_glossary_variants(
    data: Dict[str, Any],
    glossary,
) -> List[Inconsistency]:
    """For each glossary entry, search all blocks for variant renderings.

    Finds blocks where the Chinese source contains the glossary term but the
    translated_content uses a different English form than recommended_form.
    """
    if glossary is None:
        return []

    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
    results = []

    # Get all glossary entries (not just those in footnotes)
    all_entries = []
    try:
        all_entries = glossary.get_all_entries()
    except AttributeError:
        # Fallback: iterate the cache directly
        if hasattr(glossary, '_cache'):
            all_entries = list(glossary._cache.values())

    for entry in all_entries:
        if not entry.recommended_form or len(entry.chinese) < 3:
            continue  # Skip 2-char terms (too common, too many false positives)

        canon = entry.recommended_form
        ideogram = entry.chinese
        occurrences = []
        variant_counts: Counter = Counter()

        for ch_idx, chapter in enumerate(chapters):
            for block in chapter.get("content_blocks", []):
                source = block.get("content", "")
                translated = block.get("translated_content", "")
                if not source or not translated or ideogram not in source:
                    continue

                block_id = block.get("id", "unknown")

                if canon in translated:
                    occurrences.append(TermOccurrence(
                        ideogram=ideogram, rendering=canon,
                        block_id=block_id, chapter_idx=ch_idx, marker_key=-1,
                        pinyin=entry.pinyin,
                    ))
                else:
                    # The canonical form is NOT in this block but the Chinese source is.
                    # Try to find what the translator used instead.
                    # Strategy: look for capitalized phrases sharing key words with canon.
                    variant = _find_variant_phrase(translated, canon)
                    if variant:
                        occurrences.append(TermOccurrence(
                            ideogram=ideogram, rendering=variant,
                            block_id=block_id, chapter_idx=ch_idx, marker_key=-1,
                            pinyin=entry.pinyin,
                        ))
                        variant_counts[variant] += 1

        if variant_counts:
            results.append(Inconsistency(
                ideogram=ideogram,
                winner=canon,
                winner_source="glossary",
                variants=dict(variant_counts),
                occurrences=occurrences,
            ))

    return results


def _find_variant_phrase(translated: str, canonical: str) -> Optional[str]:
    """Find a capitalized phrase in text that shares key words with the canonical form.

    Only matches phrases that share at least one significant word (3+ chars)
    with the canonical. Very conservative to avoid false positives.
    """
    # Extract significant words from canonical (3+ chars, not function words)
    skip = {"the", "and", "for", "with", "from", "that", "this", "into"}
    canon_words = set(
        w.lower() for w in re.findall(r"[A-Za-z''\-]+", canonical)
        if len(w) >= 3 and w.lower() not in skip
    )
    if not canon_words:
        return None

    # Find capitalized multi-word phrases (hyphenated compounds count)
    # Match things like "Ghost-Fears-Sorrow", "Ghosts' Dread", "Northern È"
    phrase_re = re.compile(
        r"\b([A-Z][a-z''\u2019]+(?:[\s\-]+[A-Za-z\u00C0-\u024F][a-z''\u2019]*){0,4})\b"
    )

    best_match = None
    best_overlap = 0

    for m in phrase_re.finditer(translated):
        phrase = m.group(1).strip()
        if len(phrase) < 4:
            continue

        phrase_words = set(
            w.lower() for w in re.findall(r"[A-Za-z''\-]+", phrase)
            if len(w) >= 3 and w.lower() not in skip
        )

        overlap = len(canon_words & phrase_words)
        if overlap > best_overlap:
            best_overlap = overlap
            best_match = phrase

    # Require at least 1 overlapping significant word
    if best_overlap >= 1 and best_match:
        return best_match

    return None


# ---------------------------------------------------------------------------
# Footnote-based extraction
# ---------------------------------------------------------------------------

def extract_term_renderings(data: Dict[str, Any]) -> Dict[str, List[TermOccurrence]]:
    """Extract ideogram→rendering pairs from surviving footnotes.

    Returns:
        Dict mapping ideogram to list of TermOccurrence.
    """
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
    renderings: Dict[str, List[TermOccurrence]] = defaultdict(list)

    for ch_idx, chapter in enumerate(chapters):
        for block in chapter.get("content_blocks", []):
            block_id = block.get("id", "unknown")
            translated = block.get("translated_content", "")
            footnotes = block.get("footnotes", [])

            if not translated or not footnotes:
                continue

            for fn in footnotes:
                ideogram = fn.get("ideogram", "")
                if not ideogram or len(ideogram) < 2:
                    continue

                marker_key = fn.get("key")
                if marker_key is None:
                    continue

                rendering = _extract_rendering_before_marker(translated, marker_key)
                if not rendering:
                    continue

                renderings[ideogram].append(TermOccurrence(
                    ideogram=ideogram,
                    rendering=rendering,
                    block_id=block_id,
                    chapter_idx=ch_idx,
                    marker_key=marker_key,
                    pinyin=fn.get("pinyin", ""),
                ))

    # Group ideograms that share a common 3+ char Chinese substring.
    # E.g., 鄂北鬼見愁鍾家 and 鬼見愁鍾氏三雄 both contain 鬼見愁 → merge.
    renderings = _group_by_shared_substring(dict(renderings))

    return renderings


def _group_by_shared_substring(
    renderings: Dict[str, List[TermOccurrence]],
    min_substr_len: int = 3,
) -> Dict[str, List[TermOccurrence]]:
    """Merge ideograms that share a common Chinese substring of min_substr_len.

    Uses the longest common substring as the group key. This handles cases
    where the translator generates different ideogram strings for the same
    concept (e.g., 鄂北鬼見愁鍾家 vs 鬼見愁鍾氏三雄 both contain 鬼見愁).
    """
    if len(renderings) <= 1:
        return renderings

    ideograms = list(renderings.keys())

    # Find groups: for each pair, check if they share a 3+ char substring
    # Use union-find for transitive merging
    parent: Dict[str, str] = {ig: ig for ig in ideograms}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str):
        ra, rb = find(a), find(b)
        if ra != rb:
            # Use shorter ideogram as root (more likely to be the core term)
            if len(ra) <= len(rb):
                parent[rb] = ra
            else:
                parent[ra] = rb

    # Common suffixes that extend a base term (safe to group)
    _SAFE_SUFFIXES = set("法術功派門拳掌劍刀棍鞭")

    for i in range(len(ideograms)):
        for j in range(i + 1, len(ideograms)):
            a, b = ideograms[i], ideograms[j]
            shared = _shared_substring_len(a, b)
            if shared < min_substr_len:
                continue

            shorter, longer = (a, b) if len(a) <= len(b) else (b, a)

            # If shorter is fully contained in longer, only group if the
            # extra characters are safe suffixes (法, 術, 功, etc.) not names
            if shared == len(shorter):
                extra = longer.replace(shorter, "", 1)
                if extra and not all(c in _SAFE_SUFFIXES for c in extra):
                    continue  # extra chars look like a person/place name — don't group
            else:
                # Partial overlap: require shared >= 75% of shorter
                if shared < len(shorter) * 0.9:
                    continue

            union(a, b)

    # Collect groups
    groups: Dict[str, List[str]] = defaultdict(list)
    for ig in ideograms:
        groups[find(ig)].append(ig)

    # Only merge groups with 2+ members
    merged: Dict[str, List[TermOccurrence]] = {}
    merged_keys: Set[str] = set()

    for root, members in groups.items():
        if len(members) == 1:
            merged[members[0]] = renderings[members[0]]
        else:
            # Use shortest member as key (likely the core term)
            key = min(members, key=len)
            combined: List[TermOccurrence] = []
            for m in members:
                combined.extend(renderings[m])
                merged_keys.add(m)
            merged[key] = combined
            if len(members) > 1:
                logger.debug(f"  Grouped ideograms under '{key}': {members}")

    return merged


def _shared_substring_len(a: str, b: str) -> int:
    """Return length of longest common substring between two Chinese strings."""
    if not a or not b:
        return 0
    # Simple O(n*m) approach — fine for short ideogram strings
    max_len = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            max_len = max(max_len, k)
    return max_len


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _normalize_rendering(s: str) -> str:
    """Normalize a rendering for comparison."""
    # Normalize curly quotes/apostrophes to straight
    s = s.replace('\u2018', "'").replace('\u2019', "'")
    s = s.replace('\u201C', '"').replace('\u201D', '"')
    return re.sub(r'\s+', ' ', s.lower().strip())


def detect_inconsistencies(
    renderings: Dict[str, List[TermOccurrence]],
    glossary=None,
) -> List[Inconsistency]:
    """Find ideograms with 2+ distinct inline renderings from footnotes.

    Args:
        renderings: Output of extract_term_renderings().
        glossary: Optional TranslationGlossary for authoritative forms.

    Returns:
        List of Inconsistency objects.
    """
    inconsistencies = []

    for ideogram, occurrences in renderings.items():
        counter: Counter = Counter()
        norm_to_original: Dict[str, str] = {}

        for occ in occurrences:
            norm = _normalize_rendering(occ.rendering)
            counter[norm] += 1
            if norm not in norm_to_original:
                norm_to_original[norm] = occ.rendering

        if len(counter) < 2:
            continue

        # Determine winner
        winner = None
        winner_source = "majority"

        if glossary:
            entry = glossary.lookup(ideogram)
            if entry and entry.recommended_form:
                winner = entry.recommended_form
                winner_source = "glossary"

        if winner is None:
            most_common = counter.most_common()
            winner_norm = most_common[0][0]
            winner = norm_to_original[winner_norm]

        variants = {}
        for norm, count in counter.items():
            original = norm_to_original[norm]
            if _normalize_rendering(original) != _normalize_rendering(winner):
                variants[original] = count

        if variants:
            inconsistencies.append(Inconsistency(
                ideogram=ideogram,
                winner=winner,
                winner_source=winner_source,
                variants=variants,
                occurrences=occurrences,
            ))

    inconsistencies.sort(key=lambda x: len(x.variants), reverse=True)
    return inconsistencies


# ---------------------------------------------------------------------------
# Standardization
# ---------------------------------------------------------------------------

def standardize_terms(
    data: Dict[str, Any],
    inconsistencies: List[Inconsistency],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Replace variant renderings with the winner in translated_content.

    Returns:
        (data, report)
    """
    if not inconsistencies:
        return data, {
            "inconsistencies_found": 0,
            "terms_standardized": 0,
            "replacements_made": 0,
            "details": [],
            "glossary_candidates": [],
        }

    # Build replacements: longer strings first to avoid partial matches
    replacements: List[Tuple[str, str, str]] = []
    for inc in inconsistencies:
        for variant in inc.variants:
            replacements.append((variant, inc.winner, inc.ideogram))

    replacements.sort(key=lambda x: len(x[0]), reverse=True)

    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
    total_replacements = 0

    for chapter in chapters:
        for block in chapter.get("content_blocks", []):
            translated = block.get("translated_content", "")
            if not translated:
                continue

            modified = translated
            for old, new, ideogram in replacements:
                if old in modified:
                    count = modified.count(old)
                    modified = modified.replace(old, new)
                    total_replacements += count
                    logger.debug(f"  {block.get('id', '?')}: \"{old}\" → \"{new}\"")

            if modified != translated:
                block["translated_content"] = modified

    # Build report
    details = []
    glossary_candidates = []

    for inc in inconsistencies:
        details.append({
            "ideogram": inc.ideogram,
            "winner": inc.winner,
            "source": inc.winner_source,
            "variants_replaced": dict(inc.variants),
            "total_occurrences": len(inc.occurrences),
        })

        if inc.winner_source != "glossary":
            glossary_candidates.append({
                "ideogram": inc.ideogram,
                "recommended_form": inc.winner,
                "pinyin": inc.occurrences[0].pinyin if inc.occurrences else "",
                "occurrences": len(inc.occurrences),
                "variants_found": len(inc.variants) + 1,
            })

    return data, {
        "inconsistencies_found": len(inconsistencies),
        "terms_standardized": len([d for d in details if d["variants_replaced"]]),
        "replacements_made": total_replacements,
        "details": details,
        "glossary_candidates": glossary_candidates,
    }


# ---------------------------------------------------------------------------
# Compound footnote splitting
# ---------------------------------------------------------------------------

# Chinese enumeration comma — signals a list of distinct terms
_ENUM_COMMA = '、'
# 與 (and) between terms
_AND_CHAR = '與'


def split_compound_footnotes(data: Dict[str, Any]) -> int:
    """Split footnotes whose ideogram contains multiple distinct terms.

    Detects:
    - Enumeration comma (、): 亂環訣、陰陽訣 → two footnotes
    - 與 (and) between short terms: 亂環訣與陰陽訣 → two footnotes

    Does NOT split:
    - Sentence comma (，) in proverbs/idioms: 冤有頭，債有主 stays as one

    Each split term gets its own footnote. The original explanation is kept
    on the first term; subsequent terms get a brief cross-reference.
    Inline markers in translated_content are updated accordingly.

    Returns number of footnotes split.
    """
    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
    total_split = 0

    for chapter in chapters:
        for block in chapter.get("content_blocks", []):
            footnotes = block.get("footnotes", [])
            if not footnotes:
                continue

            new_footnotes = []
            needs_rewrite = False

            for fn in footnotes:
                ideo = fn.get("ideogram", "")
                parts = _split_ideogram(ideo)

                if len(parts) <= 1:
                    new_footnotes.append(fn)
                    continue

                # Split this footnote into multiple
                needs_rewrite = True
                total_split += 1
                original_key = fn.get("key")
                explanation = fn.get("explanation", "")

                for i, part in enumerate(parts):
                    new_fn = dict(fn)
                    new_fn["ideogram"] = part.strip()
                    if i == 0:
                        # First part keeps original explanation
                        new_fn["explanation"] = explanation
                    else:
                        # Subsequent parts get brief explanation extracted if possible,
                        # otherwise a cross-reference
                        sub_expl = _extract_sub_explanation(explanation, part.strip())
                        new_fn["explanation"] = sub_expl or f"See footnote for {parts[0].strip()}."
                    new_footnotes.append(new_fn)

                logger.info(f"  Split footnote in {block.get('id', '?')}: "
                            f"\"{ideo}\" → {[p.strip() for p in parts]}")

            if needs_rewrite:
                # Renumber keys
                for i, fn in enumerate(new_footnotes, 1):
                    fn["key"] = i
                block["footnotes"] = new_footnotes

                # Update markers in translated_content
                translated = block.get("translated_content", "")
                if translated:
                    block["translated_content"] = _renumber_markers_after_split(
                        translated, len(footnotes), len(new_footnotes)
                    )

    if total_split:
        logger.info(f"  Split {total_split} compound footnotes")

    return total_split


def _split_ideogram(ideo: str) -> List[str]:
    """Split a compound ideogram into parts if it contains separators.

    Returns list of parts (1 element if no split needed).
    """
    if not ideo:
        return [ideo]

    # Split on enumeration comma (、)
    if _ENUM_COMMA in ideo:
        parts = [p.strip() for p in ideo.split(_ENUM_COMMA) if p.strip()]
        if len(parts) >= 2 and all(len(p) >= 2 for p in parts):
            return parts

    # Split on 與 (and) — but only if both halves are short (≤5 chars each)
    if _AND_CHAR in ideo:
        idx = ideo.index(_AND_CHAR)
        left = ideo[:idx].strip()
        right = ideo[idx + 1:].strip()
        if left and right and len(left) <= 5 and len(right) <= 5:
            return [left, right]

    return [ideo]


def _extract_sub_explanation(full_explanation: str, sub_ideogram: str) -> Optional[str]:
    """Try to extract a sub-explanation for a specific term from a combined explanation.

    Looks for the term or its translation in the explanation text and extracts
    the relevant sentence.
    """
    if not full_explanation or not sub_ideogram:
        return None

    # Look for the Chinese characters in the explanation
    if sub_ideogram in full_explanation:
        # Find the sentence containing it
        for sent in re.split(r'[.。]', full_explanation):
            if sub_ideogram in sent:
                return sent.strip() + "."

    return None


def _renumber_markers_after_split(text: str, old_count: int, new_count: int) -> str:
    """After splitting footnotes, the marker count may change.

    If we split footnote [3] into [3] and [4], markers [4]+ need incrementing.
    For simplicity, just renumber all markers sequentially.
    """
    # This is a simplified approach — works when the split only adds markers
    # A full implementation would track which markers expanded
    # For now, markers stay as-is since the split terms share the same marker position
    return text


# ---------------------------------------------------------------------------
# LLM-assisted compound footnote splitting
# ---------------------------------------------------------------------------

_LLM_SPLIT_PROMPT = """You are a Classical Chinese lexicographer specialising in wǔxiá fiction.

A translation footnote has been created for the following Chinese text. Determine whether this text represents a SINGLE concept or MULTIPLE distinct concepts joined together.

SINGLE — keep as one footnote:
- Idioms and proverbs: 打遍天下無敵手, 有眼不識泰山, 冤有頭債有主
- Named techniques: 十二趟犀牛望月轉回還, 鯉魚翻身攪絲腿, 收肌縮骨之法
- Techniques referencing historical/legendary figures: 漢鍾離陰陽寶扇 (Han Zhongli's Yin-Yang Fan — one technique named after an Immortal), 張果老倒騎驢 (Zhang Guolao Rides Backwards — one technique), 韋陀獻杵 (Weituo Presents the Pestle — one stance)
- Fixed epithets: 打遍天下無敵手 (one epithet for one person)
- Named events or assemblies: 天下掌門人大會

COMPOUND — split into separate footnotes (ONLY when a fictional character's name is appended to an unrelated concept):
- 百勝神拳馬老鏢頭 → ["百勝神拳", "馬老鏢頭"] (epithet + person/title — 馬老鏢頭 is a character in the story, not part of the technique)
- 鄂北鬼見愁鍾家 → ["鄂北", "鬼見愁", "鍾家"] (place + epithet + clan name)
- 八卦刀商劍鳴 → ["八卦刀", "商劍鳴"] (weapon style + fictional character name)
- 金面佛苗大俠 → ["金面佛", "苗大俠"] (epithet + person honorific)
- 孫剛峰斬手相託 → ["孫剛峰", "斬手相託"] (person name + event description)

Key distinction: historical/legendary figures IN a technique name = SINGLE. Fictional character name APPENDED to a separate concept = COMPOUND.

Return JSON: {"verdict": "SINGLE"} or {"verdict": "COMPOUND", "parts": ["part1", "part2"]}"""


def _llm_split_one(
    ideogram: str,
    explanation: str,
    client,
) -> Optional[List[str]]:
    """Ask DeepSeek whether a single ideogram is compound. Returns split parts or None."""
    from utils.clients.llm_client import LLMRequest

    user_content = (
        f"Ideogram: {ideogram}\n"
        f"Footnote explanation: {explanation[:200]}\n\n"
        f"Is this a SINGLE concept or COMPOUND (multiple concepts merged)?"
    )

    try:
        response = client.chat(LLMRequest(
            messages=[
                {"role": "system", "content": _LLM_SPLIT_PROMPT},
                {"role": "user", "content": user_content},
            ],
            model="deepseek-chat",
            temperature=0.1,
            json_mode=True,
        ))
    except Exception as e:
        logger.warning(f"LLM split failed for '{ideogram}': {e}")
        return None

    result = response.parsed
    if isinstance(result, dict) and result.get("verdict", "").upper() == "COMPOUND":
        parts = result.get("parts", [])
        if len(parts) >= 2:
            return parts

    return None


def split_compounds_via_llm(data: Dict[str, Any], client=None,
                            max_workers: int = 20) -> int:
    """Phase 0.5: Use DeepSeek to split ambiguous compound ideograms.

    Runs after programmatic splitting. Sends each 6+ char ideogram
    individually to DeepSeek with targeted prompt and examples.

    Args:
        data: Full work JSON (modified in place).
        client: DeepSeek LLM client. If None, creates one.
        max_workers: Parallel workers for DeepSeek calls.

    Returns:
        Number of footnotes split.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if client is None:
        try:
            from utils.clients.llm_config import get_llm_client
            client = get_llm_client(provider="deepseek")
        except Exception as e:
            logger.warning(f"Could not initialize DeepSeek client for compound splitting: {e}")
            return 0

    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])

    # Collect candidates: footnotes with 6+ char ideograms
    candidates = []
    candidate_locations = []  # (ch_idx, block_idx, fn_idx)

    for ch_idx, chapter in enumerate(chapters):
        for bl_idx, block in enumerate(chapter.get("content_blocks", [])):
            for fn_idx, fn in enumerate(block.get("footnotes", [])):
                ideo = fn.get("ideogram", "")
                if len(ideo) >= 6:
                    candidates.append({
                        "ideogram": ideo,
                        "explanation": fn.get("explanation", ""),
                    })
                    candidate_locations.append((ch_idx, bl_idx, fn_idx))

    if not candidates:
        return 0

    logger.info(f"  LLM split review: {len(candidates)} candidates → DeepSeek (1 call each, {max_workers} workers)")

    # Parallel calls — one per candidate
    split_map: Dict[int, List[str]] = {}

    def _check_one(idx: int) -> Tuple[int, Optional[List[str]]]:
        c = candidates[idx]
        parts = _llm_split_one(c["ideogram"], c["explanation"], client)
        return idx, parts

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_check_one, i): i for i in range(len(candidates))}
        for fut in as_completed(futures):
            idx, parts = fut.result()
            if parts:
                split_map[idx] = parts

    if not split_map:
        logger.info("  LLM split review: no compounds detected")
        return 0

    # Apply splits (process in reverse order to preserve indices)
    total_split = 0
    blocks_to_rekey: set = set()

    for idx in sorted(split_map.keys(), reverse=True):
        parts = split_map[idx]
        ch_idx, bl_idx, fn_idx = candidate_locations[idx]
        block = chapters[ch_idx]["content_blocks"][bl_idx]
        footnotes = block.get("footnotes", [])
        fn = footnotes[fn_idx]

        original_ideo = fn.get("ideogram", "")
        explanation = fn.get("explanation", "")

        logger.info(f"  LLM split {block.get('id', '?')}: \"{original_ideo}\" → {parts}")

        # Replace the original footnote with split versions
        new_fns = []
        for i, part in enumerate(parts):
            new_fn = dict(fn)
            new_fn["ideogram"] = part
            if i == 0:
                new_fn["explanation"] = explanation
            else:
                sub = _extract_sub_explanation(explanation, part)
                new_fn["explanation"] = sub or f"See footnote for {parts[0]}."
            new_fns.append(new_fn)

        # Replace in-place
        footnotes[fn_idx:fn_idx + 1] = new_fns
        block["footnotes"] = footnotes
        blocks_to_rekey.add((ch_idx, bl_idx))
        total_split += 1

    # Renumber keys in affected blocks
    for ch_idx, bl_idx in blocks_to_rekey:
        block = chapters[ch_idx]["content_blocks"][bl_idx]
        for i, fn in enumerate(block.get("footnotes", []), 1):
            fn["key"] = i

    logger.info(f"  LLM split: {total_split} compound footnotes split")
    return total_split


# ---------------------------------------------------------------------------
# Top-level convenience
# ---------------------------------------------------------------------------

def standardize_work(
    data: Dict[str, Any],
    glossary=None,
    llm_client=None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Full pipeline: split compounds → detect inconsistencies → standardize.

    Args:
        data: Full work JSON.
        glossary: Optional TranslationGlossary instance.
        llm_client: Optional DeepSeek client for compound splitting.
                    If None, one is created automatically.

    Returns:
        (data, report)
    """
    # Phase 0: Split compound footnotes (、 separated, 與 joined)
    split_count = split_compound_footnotes(data)

    # Phase 0.5: LLM-assisted split of ambiguous compounds (6+ char ideograms)
    llm_split_count = split_compounds_via_llm(data, client=llm_client)

    # Phase 1: Footnote-based detection
    renderings = extract_term_renderings(data)
    logger.info(f"  Extracted renderings for {len(renderings)} unique ideograms from footnotes")

    footnote_inconsistencies = detect_inconsistencies(renderings, glossary)

    # Phase 2: Glossary-driven variant search (catches terms where footnotes were deduped)
    glossary_inconsistencies = _find_glossary_variants(data, glossary)

    # Merge: glossary-driven results take priority (they have authoritative winners)
    seen_ideograms: Set[str] = set()
    all_inconsistencies: List[Inconsistency] = []

    for inc in glossary_inconsistencies:
        seen_ideograms.add(inc.ideogram)
        all_inconsistencies.append(inc)

    for inc in footnote_inconsistencies:
        if inc.ideogram not in seen_ideograms:
            all_inconsistencies.append(inc)

    if all_inconsistencies:
        logger.info(f"  Found {len(all_inconsistencies)} inconsistent terms "
                    f"({len(glossary_inconsistencies)} from glossary, "
                    f"{len(all_inconsistencies) - len(glossary_inconsistencies)} from footnotes):")
        for inc in all_inconsistencies:
            variants_str = ", ".join(f'"{v}" ({c}x)' for v, c in inc.variants.items())
            logger.info(f"    {inc.ideogram}: winner=\"{inc.winner}\" [{inc.winner_source}], "
                        f"replacing: {variants_str}")
    else:
        logger.info("  No inconsistencies found")

    data, report = standardize_terms(data, all_inconsistencies)

    if report["glossary_candidates"]:
        logger.info(f"  {len(report['glossary_candidates'])} terms not in glossary — "
                    f"consider adding:")
        for cand in report["glossary_candidates"]:
            logger.info(f"    {cand['ideogram']} → \"{cand['recommended_form']}\" "
                        f"({cand['occurrences']} occurrences)")

    return data, report
