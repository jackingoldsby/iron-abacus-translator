"""
Chapter-Level Consistency Reviewer

Reviews translated chapters for cross-block consistency issues that are
invisible at the block level: tense shifts, gender pronoun confusion,
register breaks, missing footnotes, and pinyin errors.

Reads the whole chapter for context but produces block-level replacement
suggestions with corrected translated_content and properly positioned footnotes.

Usage:
    from processors.consistency_reviewer import ConsistencyReviewer

    reviewer = ConsistencyReviewer(model="deepseek-chat", provider="deepseek")
    report = reviewer.review_chapter(chapter, chapter_idx=3, work_id="D60")
    reports = reviewer.review_work(data, work_id="D60")
    data = reviewer.apply_findings(data, reports)
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Categories and their descriptions for the review prompt
REVIEW_CATEGORIES = {
    "tense": "Past/present mixing within a passage, inconsistent tense across chapter, tense drift in retrospective narration",
    "gender": "He/she/his/her pronoun confusion — verify against Chinese source (他 vs 她 vs 它). Also: gendered collective nouns (二人/眾人 as 'two men' instead of gender-neutral)",
    "style": "Register breaks, anachronistic phrasing, inconsistency with author/genre conventions, paratactic chains not restructured, dangling modifiers, ambiguous pronoun reference",
    "register": "Modern English in jianghu context: 'heist', 'mark', 'gang', 'Messrs.', 'a cut above', corporate/legal/casual English where period register expected. Also: European supernatural ('goblins') in Chinese settings",
    "honorific": "English translations where pinyin honorific expected (*Shīxiōng* not 'Senior Brother', *Bāngzhǔ* not 'Clan Leader'). Also: translated surnames (熊 as 'Bear')",
    "footnote": "Missing footnotes on culturally significant terms (first occurrence, not in suppress list). Missing acupoint footnotes, missing sect footnotes, missing classical allusion footnotes",
    "pinyin": "Missing tone marks, incorrect romanization, inconsistent formatting, tone marks on English words, inconsistent compound spacing",
    "date": "Incorrect reign year → CE conversion in footnotes (e.g. 康熙十四年 should be 1675 CE, not 1676)",
    "weapon": "Weapon translation errors: 長劍 as 'long sword', 寶劍 overriding established weapon type, 棒 as 'cudgel' in domestic context, weapon idioms translated literally (戟指 as 'halberd-like finger')",
    "idiom": "Literal calque of Chinese idiom/curse where English intent-translation needed: 短命的 as 'short-lived', 他奶奶的 as 'his grandmother's', 喝錯了醋 as 'mistake your vinegar'",
    "name": "Character name error — personal name in English doesn't match the Chinese source ideograms (e.g. 苗人鳳 rendered as Miáo Gūniáng instead of Miáo Rénfèng)",
    "char_count": "Reference to number of Chinese characters/words without footnote breakdown (e.g. 'thirteen characters' with no footnote giving the original ideograms)",
    "formula_pinyin": "Martial formula, couplet, or mnemonic (口訣) left as pinyin instead of translated to English — these must convey meaning to the reader",
}

SEVERITY_LEVELS = ("error", "warning", "info")


def _extract_json(text: str) -> Optional[dict]:
    """Extract JSON from a response that may be wrapped in markdown or truncated."""
    if not text:
        return None
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting from ```json ... ``` blocks
    match = re.search(r'```(?:json)?\s*\n(.*?)\n\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Try finding the first { ... } block
    start = text.find('{')
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
    # Truncated response — salvage complete findings from partial JSON
    salvaged = _salvage_truncated_findings(text)
    if salvaged:
        logger.warning(f"Salvaged {len(salvaged)} findings from truncated response")
        return {"findings": salvaged}
    logger.warning(f"Could not extract JSON from response ({len(text)} chars)")
    return None


def _salvage_truncated_findings(text: str) -> Optional[list]:
    """Extract complete finding objects from truncated JSON array.

    When DeepSeek hits max_tokens mid-response, we lose the trailing
    entries but can still recover all complete JSON objects from the
    findings array.
    """
    # Find the start of the findings array
    match = re.search(r'"findings"\s*:\s*\[', text)
    if not match:
        return None
    array_start = match.end()

    findings = []
    depth = 0
    obj_start = None

    for i in range(array_start, len(text)):
        ch = text[i]
        if ch == '{' and depth == 0:
            obj_start = i
            depth = 1
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and obj_start is not None:
                try:
                    obj = json.loads(text[obj_start:i + 1])
                    findings.append(obj)
                except json.JSONDecodeError:
                    pass
                obj_start = None
        # Handle strings (skip braces inside strings)
        elif ch == '"' and depth > 0:
            # Skip to end of string
            j = i + 1
            while j < len(text):
                if text[j] == '\\':
                    j += 2
                elif text[j] == '"':
                    break
                else:
                    j += 1
            # We can't easily advance i in this loop, so this is approximate.
            # The json.loads call will reject malformed objects anyway.

    return findings if findings else None


def _build_system_prompt(genre_brief: str, suppress_ideograms: Set[str]) -> str:
    """Build the system prompt for the consistency reviewer."""
    suppress_sample = ", ".join(sorted(suppress_ideograms)[:30])
    suppress_note = (
        f"The following terms are SUPPRESSED and should NOT be suggested as missing footnotes "
        f"(there are {len(suppress_ideograms)} total; sample: {suppress_sample}...)."
        if suppress_ideograms else
        "No suppress list provided."
    )

    return f"""You are a ruthlessly thorough senior literary editor reviewing an English translation of a Classical Chinese novel. Your job is to catch EVERY genuine consistency issue in this chapter. Err on the side of flagging too much rather than too little — but every finding must reflect a real problem, not a stylistic preference.

## Genre/Register Context
{genre_brief}

## Review Categories — Be Exhaustive

1. **tense** — {REVIEW_CATEGORIES['tense']}
   - Read EVERY paragraph closely. Check whether the passage uses past or present tense, then verify that EVERY verb in the block is consistent.
   - Mixed tense within a single action sequence is ALWAYS an error.
   - If surrounding blocks use past tense and one block suddenly switches to present (or vice versa), flag it.
   - Check participles, conditionals, and reported speech for tense agreement too.
   - BUT: deliberate tense shifts are legitimate in certain contexts:
     - Present tense in dialogue or direct speech is normal even in past-tense narrative.
     - Present tense for habitual or ongoing states ("most young men have learned...") is correct.
     - Present tense in a character's internal monologue can reflect immediacy of thought at the time.
     - Conditional constructions ("should X happen") can use present tense within past narrative.
   - Only flag tense issues where the shift is clearly unintentional and creates confusion.

1b. **name accuracy** — Cross-check character names in the English against the Chinese source. Flag any block where a character's personal name (given name or full name) has been replaced with a different word — especially honorifics, titles, or common nouns. Example: 苗人鳳 (Miáo Rénfèng) rendered as "Miáo *Gūniáng*" is a critical error — 姑娘 means "young lady" and is NOT part of this character's name. Compare the pinyin in the English against the ideograms in the source. If a name appears correctly in other blocks but differently in this block, flag it. This is a **severity: error**.

2. **gender** — {REVIEW_CATEGORIES['gender']}
   - IMPORTANT: Check the Chinese source. 他 = he/him/his, 她 = she/her, 它 = it/its.
   - Flag EVERY instance where the English pronoun contradicts the Chinese source character.
   - Also flag cases where the referent is ambiguous but context makes the gender clear.
   - Check possessives (his/her), reflexives (himself/herself), and object pronouns (him/her) — not just subjects.
   - BUT: titles and honorifics (Madam, Mistress, Master) used as forms of address are NOT gender errors — they reflect social hierarchy and are valid stylistic choices.

3. **style** — {REVIEW_CATEGORIES['style']}
   - Flag genuinely modern/anachronistic phrasing that no wuxia translation would use: "totally", "cool", "okay", "stuff", "dude", "awesome".
   - Flag mistranslations where the English meaning diverges from the Chinese source.
   - BUT: respect the register of the genre. Wuxia translations have their own conventions:
     - Expletives like "damn it" or "blast" are standard in wuxia translation — do NOT flag them.
     - Sino-English calques that preserve Chinese flavor are often deliberate: "ten thousand misfortunes", "under heaven", "shook the life from" — these are features, not bugs.
     - Idioms translated literally to preserve Chinese texture (e.g. 易如反掌 as "as easy as turning over her hand") are valid choices when the meaning is clear.
     - Different address forms for the same character (name vs title vs epithet) are normal in Chinese fiction and reflect social context — do NOT flag variation as inconsistency.
   - Only flag style issues where a native English reader would genuinely stumble or where the register breaks in a way that damages the reading experience.

3a. **register** — {REVIEW_CATEGORIES['register']}
   - Flag modern crime slang in jianghu context: "heist," "mark," "gang," "gig," "score," "racket."
   - Flag formal/business English in martial dialogue: "Messrs.," "aforementioned," "hereby."
   - Flag modern casual idioms: "a cut above," "top-notch," "spot-on," "level up."
   - Flag European supernatural creatures substituted for Chinese: "goblins" for 鬼, "elves" for 精.
   - Test: if the word fits a modern crime thriller or corporate memo, it's wrong for wuxia.
   - BUT: mildly archaic English ("skulk," "ere," "forthwith") is appropriate for wuxia register — do NOT flag it.

3b. **honorific** — {REVIEW_CATEGORIES['honorific']}
   - Honorifics must be italicized pinyin per project convention: *Shīxiōng*, *Gūniáng*, *Bāngzhǔ*, *Zhǎngmén*, *Zhuāngzhǔ*.
   - Flag any English translation of an honorific: "Senior Brother" (should be *Shīxiōng*), "Clan Leader" (should be *Bāngzhǔ*), "Village Master" (should be *Zhuāngzhǔ* — and 莊 is "manor" not "village").
   - Flag translated surnames: 熊 as "Bear" (should be Xióng), 馬 as "Horse" (should be Mǎ).
   - Martial-lineage terms (師兄, 師父, 前輩, 掌門, 幫主) stay pinyin even in third-person narration.
   - Social honorifics (姑娘, 大哥, 夫人) are pinyin in address, English ok in narration.

3b2. **formula_pinyin** — {REVIEW_CATEGORIES['formula_pinyin']}
   - Martial formulae, couplets, and mnemonics (口訣) must be TRANSLATED to English, not left as pinyin. These are meant to convey meaning — the reader needs to understand the combat instruction or poetic imagery. Flag any martial rhyme or mnemonic rendered as pinyin instead of English. The pinyin should go in a footnote with the original Chinese.
   - Examples: combat couplets recited by characters, training mnemonics, rhyming martial instructions, inscription verses on weapons or scrolls.
   - This is severity: **error**.

3c. **weapon** — {REVIEW_CATEGORIES['weapon']}
   - 長劍 = "sword" not "long sword" (it's the default jiàn).
   - 寶劍 must track the actual weapon held — don't reclassify a dagger as a sword.
   - 棒 in domestic context = "poker" not "cudgel" (撥火棒 = "fire poker").
   - 錐 as thrown hidden weapon = "dart" not "spike."
   - Weapon characters used as idioms: 戟指 = "jabbed a finger" NOT "pointed with a halberd-like finger."
   - Technique names must be dignified and physically accurate: 吐 = "project/lash" not "spit."

3d. **idiom** — {REVIEW_CATEGORIES['idiom']}
   - Chinese curses translated literally: 短命的 as "short-lived villain" (should be "accursed wretch"), 他奶奶的 as "his grandmother's" (should be "goddamn").
   - 操他奶奶的熊 = "Fuck that gutless wretch!" NOT "Fuck his grandmother's bear!" (熊 = coward, not bear).
   - Chinese idioms that are dead calques in English: 喝錯了醋 as "mistake your vinegar" (should be "misdirect your anger").
   - Body-organ metaphors translated literally: "gall bladders quivered" (should be "courage failed them" with footnote).

4. **footnote** — {REVIEW_CATEGORIES['footnote']}
   - Suggest footnotes for genuinely culturally significant terms: historical references, Buddhist/Taoist concepts, martial arts schools and formations, classical allusions, and wuxia conventions that a Western reader would not know.
   - When multiple related terms appear close together (e.g. a school name and its signature technique), suggest a SINGLE combined footnote rather than separate ones. For example, if 八卦門 (Bāguà School) and 八卦刀 (Bāguà Sabre) appear in adjacent blocks, combine them into one footnote explaining the Bāguà tradition and noting its sabre technique — do not create two separate footnotes.
   - Do NOT suggest footnotes for:
     - Character names or terms already in the suppress list.
     - Plot-specific items (weapons, objects, letters) — these are narrative, not cultural.
     - Terms whose meaning is clear from context.
   - Martial arts technique names: do NOT add footnotes that merely restate the imagery of the name. "White Crane Spreads Wings" does not need a footnote saying it resembles a crane spreading its wings — that is tautological. Only footnote techniques when there is genuine cultural or historical significance to explain (e.g., the technique's origin in a real martial tradition, its connection to Taoist/Buddhist philosophy, or its historical context).
   - Keep footnote explanations focused on cultural/historical significance. Do NOT narrate the plot or explain what happens next.
   - {suppress_note}

4b. **char_count** — {REVIEW_CATEGORIES['char_count']}
   - When the English says "thirteen characters," "seven words," "four-line verse," or any reference to a count of Chinese characters/words/lines, there MUST be a footnote giving the original Chinese ideograms and a character-by-character breakdown. Without this, the count is meaningless to an English reader. Check the Chinese source to find the referenced text and provide it in the footnote. This is severity: **error**.

5. **pinyin** — {REVIEW_CATEGORIES['pinyin']}
   - All pinyin EVERYWHERE — in the main text AND in footnotes — MUST have tone diacritics (e.g., Wǔtái Shān, not Wutai Shan).
   - Verify romanization against the Chinese ideograms character by character.
   - Flag inconsistent romanization of the same term across blocks.

6. **date** — {REVIEW_CATEGORIES['date']}
   - Check footnotes that mention Chinese reign years (年號) and verify the CE date conversion.
   - Common reign periods: 康熙 (1662–1722), 雍正 (1723–1735), 乾隆 (1736–1795), 靖康 (1126–1127), etc.
   - The formula is: start_year + reign_year - 1 = CE year. E.g., 康熙十四年 = 1662 + 14 - 1 = 1675 CE.
   - 元年 means the first year (year 1) of a reign.
   - Flag any footnote where the CE date doesn't match the reign year calculation.
   - Also flag if a footnote mentions a reign period but doesn't include the CE date — suggest adding it.

## Severity Levels
- **error** — Clear mistake (wrong gender, factual pinyin error, obvious mistranslation, wrong tense that changes meaning)
- **warning** — Likely issue (tense inconsistency, register break, awkward phrasing)
- **info** — Recommendation (missing footnote opportunity, minor style refinement)

## Output Rules
- Each finding targets a SINGLE block (identified by block_id).
- Provide the COMPLETE replacement: `replacement_translated_content` + `replacement_footnotes`. The replacement MUST contain every sentence from the original — you are making surgical fixes, not rewriting or summarizing. If the original block has 8 sentences, your replacement must have 8 sentences. Dropping content is a critical failure.
- Footnote markers [N] go immediately after the footnoted term, outside quotes.
- Footnote keys are 1-indexed per block.
- If a block has existing footnotes that are correct, include them unchanged in `replacement_footnotes`.
- If your fix doesn't change the footnotes, set `replacement_footnotes` to the block's current footnotes.
- Be THOROUGH. Read every single block. Check every verb tense. Check every pronoun. Check every pinyin.
- Do NOT fabricate issues. Every finding must be grounded in what the text actually says. Quote the problematic phrase in your note.
- When in doubt about whether something is a deliberate stylistic choice or an error, consider whether it serves the genre. If it reads naturally in a wuxia novel, leave it alone.

## DO NOT flag these (they are correct by design):
- Wuxia epithets (Snow Mountain Flying Fox, Golden-Faced Buddha) as missing cultural footnotes — these are self-explanatory
- Register-preserving calques (芳名 → "fragrant name") — these preserve Chinese courtesy register intentionally
- Moderate variation in forms of address — characters naturally use different address forms in different contexts
- Mildly archaic English diction ("skulk," "ere," "forthwith") — appropriate for wuxia register
- Past perfect inside dialogue recounting past events ("he had been wounded") — correct English grammar
- Fictional faction names, character epithets, and plot devices as cultural terms — these are in-story, not cultural
- Honorifics rendered as italicized pinyin — this is the project convention
- Unusual but comprehensible English collocations ("coarse sabre scar") — acceptable if meaning is clear
- Footnotes that would require spoiling plot reveals"""


def _build_user_prompt(blocks_text: str, chapter_title: str) -> str:
    """Build the user prompt with the chapter content."""
    return f"""Review this chapter for consistency issues. Return a JSON object with your findings.

## Chapter: {chapter_title}

## Content (each block has ZH source + EN translation + any existing footnotes)

{blocks_text}

## Required JSON Format

Return EXACTLY this structure:
```json
{{
  "findings": [
    {{
      "block_id": "block_NNNN",
      "category": "tense|gender|name|style|register|honorific|weapon|idiom|footnote|pinyin|date|char_count|formula_pinyin",
      "severity": "error|warning|info",
      "note": "Brief explanation of the issue",
      "original_translated_content": "The original English text from the block",
      "replacement_translated_content": "The corrected English text",
      "replacement_footnotes": [
        {{
          "key": 1,
          "ideogram": "中文",
          "pinyin": "zhōngwén",
          "explanation": "Cultural explanation..."
        }}
      ]
    }}
  ]
}}
```

If there are no issues, return: {{"findings": []}}"""


def _format_block(block: dict) -> str:
    """Format a single content block for the review prompt."""
    block_id = block.get("id", block.get("block_id", "unknown"))
    zh = block.get("content", "")
    en = block.get("translated_content", "")

    if not en:
        return ""

    parts = [f"[{block_id}]", f"ZH: {zh}", f"EN: {en}"]

    footnotes = block.get("footnotes", [])
    if footnotes:
        fn_lines = []
        for fn in footnotes:
            key = fn.get("key", "?")
            ideogram = fn.get("ideogram", "")
            pinyin = fn.get("pinyin", "")
            explanation = fn.get("explanation", "")
            fn_lines.append(f"  [{key}] {ideogram} ({pinyin}): {explanation}")
        parts.append("FOOTNOTES:\n" + "\n".join(fn_lines))

    return "\n".join(parts)


def _extract_genre_brief(creative_brief: str) -> str:
    """Extract a concise register/style section from the full creative brief."""
    # Take the first ~500 chars which usually contain the style guidance
    lines = creative_brief.strip().split("\n")
    brief_lines = []
    char_count = 0
    for line in lines:
        brief_lines.append(line)
        char_count += len(line)
        if char_count > 600:
            break
    return "\n".join(brief_lines)


class ConsistencyReviewer:
    """Chapter-level consistency review using DeepSeek V3.

    Reads the whole chapter for cross-block context, but produces
    block-level replacement suggestions with corrected translated_content
    and properly positioned footnotes.
    """

    # Blocks per window. Each finding is ~400-600 output tokens, and DeepSeek
    # caps at 8192 output tokens. With ~15 findings per window worst-case,
    # 25 blocks keeps output well within budget while giving enough context.
    WINDOW_SIZE = 15
    OVERLAP = 2  # last N blocks of previous window repeated as context

    def __init__(self, model: str = "deepseek-chat", provider: str = "deepseek",
                 temperature: float = 0.2, max_workers: int = 5,
                 window_size: int = None, overlap: int = None):
        self.model = model
        self.provider = provider
        self.temperature = temperature
        self.max_workers = max_workers
        self.window_size = window_size or self.WINDOW_SIZE
        self.overlap = overlap or self.OVERLAP
        self._client = None

    def _get_client(self):
        """Lazy-init LLM client."""
        if self._client is None:
            from utils.clients.llm_config import get_llm_client
            self._client = get_llm_client(
                component="review",
                provider=self.provider,
                model=self.model,
            )
        return self._client

    def review_chapter(self, chapter: dict, chapter_idx: int,
                       work_id: str, genre: str = "wuxia",
                       suppress_ideograms: Set[str] = None,
                       genre_brief: str = None) -> dict:
        """Review a single chapter using sliding windows with overlap.

        Splits the chapter into windows of WINDOW_SIZE blocks. Each
        subsequent window includes the last OVERLAP blocks from the
        previous window so the model can see cross-boundary context.
        Findings are deduplicated by block_id (last writer wins).

        Args:
            chapter: Chapter dict with content_blocks.
            chapter_idx: 1-based chapter number.
            work_id: Work identifier (e.g. "D60").
            genre: Genre key for prompt registry lookup.
            suppress_ideograms: Set of ideograms to exclude from footnote suggestions.
            genre_brief: Pre-extracted genre/style brief. If None, uses generic wuxia.

        Returns:
            Chapter report dict matching the output schema.
        """
        blocks = chapter.get("content_blocks", [])
        translated_blocks = [b for b in blocks if b.get("translated_content")]

        if not translated_blocks:
            logger.info(f"Chapter {chapter_idx}: no translated blocks, skipping")
            return self._empty_report(work_id, chapter_idx, chapter)

        chapter_title = chapter.get("title", chapter.get("heading", f"Chapter {chapter_idx}"))

        if not genre_brief:
            genre_brief = "Standard wuxia literary register — formal martial arts prose with period-appropriate language."

        system_msg = _build_system_prompt(genre_brief, suppress_ideograms or set())

        # Build sliding windows
        windows = self._build_windows(translated_blocks)
        total_windows = len(windows)

        logger.info(f"Reviewing chapter {chapter_idx} ({len(translated_blocks)} blocks, "
                     f"{total_windows} window{'s' if total_windows != 1 else ''})")

        # Review windows in parallel
        all_findings = {}  # block_id -> finding (dedup: last writer wins)

        if total_windows == 1:
            window_blocks, reviewable_ids = windows[0]
            findings = self._review_window(
                window_blocks, reviewable_ids, chapter_idx, chapter_title,
                system_msg, 1, 1,
            )
            for f in findings:
                all_findings[f["block_id"]] = f
        else:
            with ThreadPoolExecutor(max_workers=min(total_windows, self.max_workers)) as pool:
                futures = {}
                for win_idx, (window_blocks, reviewable_ids) in enumerate(windows, 1):
                    fut = pool.submit(
                        self._review_window,
                        window_blocks, reviewable_ids, chapter_idx, chapter_title,
                        system_msg, win_idx, total_windows,
                    )
                    futures[fut] = win_idx

                for fut in as_completed(futures):
                    win_idx = futures[fut]
                    try:
                        findings = fut.result()
                        for f in findings:
                            all_findings[f["block_id"]] = f
                    except Exception as e:
                        logger.error(f"Chapter {chapter_idx} window {win_idx} failed: {e}")

        deduped = list(all_findings.values())
        logger.info(f"Chapter {chapter_idx}: {len(deduped)} findings after dedup "
                     f"(from {total_windows} windows)")

        return self._build_report(work_id, chapter_idx, chapter, deduped)

    def _build_windows(self, blocks: list) -> List[tuple]:
        """Build sliding windows with overlap.

        Returns list of (window_blocks, reviewable_block_ids) tuples.
        window_blocks: all blocks sent to the model (including overlap context).
        reviewable_block_ids: set of block_ids that are NEW in this window
            (overlap blocks are context-only, findings on them are ignored
             since they were already reviewed in the previous window).
        """
        step = self.window_size - self.overlap
        if step < 1:
            step = 1
        windows = []
        i = 0
        while i < len(blocks):
            end = min(i + self.window_size, len(blocks))
            window_blocks = blocks[i:end]

            # The first `overlap` blocks are context from previous window
            # (except for the very first window where everything is new)
            if i == 0:
                reviewable_ids = {
                    b.get("id", b.get("block_id", "")) for b in window_blocks
                }
            else:
                new_blocks = blocks[i + self.overlap:end]
                reviewable_ids = {
                    b.get("id", b.get("block_id", "")) for b in new_blocks
                }

            windows.append((window_blocks, reviewable_ids))

            if end >= len(blocks):
                break
            i += step

        return windows

    def _review_window(self, window_blocks: list, reviewable_ids: Set[str],
                       chapter_idx: int, chapter_title: str,
                       system_msg: str, win_idx: int,
                       total_windows: int) -> list:
        """Review a single window of blocks. Returns validated findings."""
        from utils.clients.llm_client import LLMRequest

        block_texts = [_format_block(b) for b in window_blocks]
        block_texts = [t for t in block_texts if t]
        blocks_text = "\n\n".join(block_texts)

        label = f"{chapter_title} (window {win_idx}/{total_windows})" if total_windows > 1 else chapter_title
        user_msg = _build_user_prompt(blocks_text, label)

        logger.info(f"  Window {win_idx}/{total_windows}: {len(window_blocks)} blocks "
                     f"({len(reviewable_ids)} reviewable)")

        try:
            client = self._get_client()
            response = client.chat(LLMRequest(
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                model=self.model,
                temperature=self.temperature,
                max_tokens=8192,
                json_mode=True,
                timeout=180,
            ))

            parsed = response.parsed
            if parsed is None:
                parsed = _extract_json(response.text)

            findings = self._parse_findings(parsed, window_blocks, chapter_idx)

            # Only keep findings for reviewable blocks (not overlap context)
            if total_windows > 1:
                before = len(findings)
                findings = [f for f in findings if f["block_id"] in reviewable_ids]
                dropped = before - len(findings)
                if dropped:
                    logger.debug(f"  Dropped {dropped} findings on overlap-context blocks")

            return findings

        except Exception as e:
            logger.error(f"Chapter {chapter_idx} window {win_idx} review failed: {e}")
            return []

    def _parse_findings(self, parsed: Optional[dict], blocks: list,
                        chapter_idx: int) -> list:
        """Parse and validate findings from LLM response."""
        if not parsed:
            logger.warning(f"Chapter {chapter_idx}: no parsed response")
            return []

        raw_findings = parsed.get("findings", [])
        if not isinstance(raw_findings, list):
            logger.warning(f"Chapter {chapter_idx}: findings is not a list")
            return []

        # Build block_id lookup for validation
        valid_block_ids = {
            b.get("id", b.get("block_id", ""))
            for b in blocks
        }

        validated = []
        for f in raw_findings:
            block_id = f.get("block_id", "")
            category = f.get("category", "")
            severity = f.get("severity", "")

            # Validate required fields
            if not block_id or not category or not severity:
                logger.debug(f"Skipping finding with missing fields: {f}")
                continue

            if category not in REVIEW_CATEGORIES:
                logger.debug(f"Skipping finding with unknown category: {category}")
                continue

            if severity not in SEVERITY_LEVELS:
                severity = "warning"  # default

            if block_id not in valid_block_ids:
                logger.debug(f"Skipping finding with unknown block_id: {block_id}")
                continue

            # Validate replacement content exists
            if not f.get("replacement_translated_content"):
                logger.debug(f"Skipping finding without replacement content: {block_id}")
                continue

            # Validate footnote markers match footnote keys
            replacement_fns = f.get("replacement_footnotes", [])
            if not isinstance(replacement_fns, list):
                replacement_fns = []

            # Ensure footnote keys are ints
            for fn in replacement_fns:
                if "key" in fn:
                    try:
                        fn["key"] = int(fn["key"])
                    except (ValueError, TypeError):
                        pass

            # Skip no-op findings where original == replacement
            original = f.get("original_translated_content", "").strip()
            replacement = f["replacement_translated_content"].strip()
            if original == replacement:
                logger.debug(f"Skipping no-op finding for {block_id}: original == replacement")
                continue

            validated.append({
                "block_id": block_id,
                "category": category,
                "severity": severity,
                "note": f.get("note", ""),
                "original_translated_content": original,
                "replacement_translated_content": replacement,
                "replacement_footnotes": replacement_fns,
                "accepted": None,
                "user_comment": "",
            })

        logger.info(f"Chapter {chapter_idx}: {len(validated)} valid findings from {len(raw_findings)} raw")
        return validated

    def _build_report(self, work_id: str, chapter_idx: int,
                      chapter: dict, findings: list) -> dict:
        """Build the chapter review report."""
        by_category = {}
        for f in findings:
            cat = f["category"]
            by_category[cat] = by_category.get(cat, 0) + 1

        chapter_title = chapter.get("title", chapter.get("heading", f"Chapter {chapter_idx}"))

        return {
            "work_id": work_id,
            "chapter": chapter_idx,
            "chapter_title": chapter_title,
            "model": self.model,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_findings": len(findings),
                "by_category": by_category,
            },
            "findings": findings,
        }

    def _empty_report(self, work_id: str, chapter_idx: int, chapter: dict) -> dict:
        """Build an empty report for chapters with no translated content."""
        return self._build_report(work_id, chapter_idx, chapter, [])

    def review_work(self, data: dict, work_id: str,
                    chapters: List[int] = None) -> List[dict]:
        """Review all (or specific) chapters in parallel. Returns list of chapter reports.

        Args:
            data: Full work data dict.
            work_id: Work identifier.
            chapters: Optional list of 1-based chapter indices to review.
                     If None, reviews all chapters.

        Returns:
            List of chapter report dicts, one per reviewed chapter.
        """
        all_chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        if not all_chapters:
            logger.warning(f"No chapters found in work {work_id}")
            return []

        # Resolve genre brief
        genre_brief = self._resolve_genre_brief(data)

        # Load suppress list
        suppress_ideograms = self._load_suppress_ideograms()

        # Select chapters to review
        if chapters:
            review_pairs = [
                (idx - 1, ch) for idx, ch in enumerate(all_chapters, 1)
                if idx in chapters and idx - 1 < len(all_chapters)
            ]
        else:
            review_pairs = list(enumerate(all_chapters))

        logger.info(f"Reviewing {len(review_pairs)} chapters for {work_id} "
                     f"(workers={self.max_workers})")

        reports = []
        if self.max_workers <= 1 or len(review_pairs) == 1:
            for list_idx, chapter in review_pairs:
                chapter_idx = list_idx + 1
                report = self.review_chapter(
                    chapter, chapter_idx, work_id,
                    suppress_ideograms=suppress_ideograms,
                    genre_brief=genre_brief,
                )
                reports.append(report)
        else:
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                futures = {}
                for list_idx, chapter in review_pairs:
                    chapter_idx = list_idx + 1
                    fut = pool.submit(
                        self.review_chapter,
                        chapter, chapter_idx, work_id,
                        suppress_ideograms=suppress_ideograms,
                        genre_brief=genre_brief,
                    )
                    futures[fut] = chapter_idx

                for fut in as_completed(futures):
                    chapter_idx = futures[fut]
                    try:
                        report = fut.result()
                        reports.append(report)
                    except Exception as e:
                        logger.error(f"Chapter {chapter_idx} review failed: {e}")
                        reports.append(self._empty_report(
                            work_id, chapter_idx,
                            all_chapters[chapter_idx - 1],
                        ))

        # Sort by chapter number
        reports.sort(key=lambda r: r["chapter"])
        return reports

    def apply_findings(self, data: dict, reports: List[dict],
                       auto_apply: List[str] = None,
                       respect_accepted: bool = True) -> dict:
        """Apply findings to the work data, replacing block content.

        Args:
            data: Full work data dict (modified in place).
            reports: List of chapter reports from review_work().
            auto_apply: List of categories to apply (e.g. ["tense", "gender", "pinyin"]).
                       If None, applies all categories.
            respect_accepted: If True (default), only apply findings where
                       ``accepted`` is True. Findings with ``accepted=None``
                       (unreviewed) are also applied. Findings with
                       ``accepted=False`` are skipped.

        Returns:
            The modified data dict.
        """
        categories = set(auto_apply) if auto_apply else set(REVIEW_CATEGORIES.keys())

        # Build a map of (chapter_idx, block_id) -> replacement from all findings
        # Key by chapter to prevent cross-chapter bleed when block IDs restart per chapter
        replacements = {}
        skipped = 0
        for report in reports:
            ch_idx = report.get("chapter", 0)  # 1-based chapter number
            for finding in report.get("findings", []):
                if finding["category"] not in categories:
                    continue
                # Respect user review decisions
                if respect_accepted and finding.get("accepted") is False:
                    skipped += 1
                    continue
                block_id = finding["block_id"]
                # Later findings for the same block override earlier ones
                replacements[(ch_idx, block_id)] = finding

        if skipped:
            logger.info(f"Skipped {skipped} rejected findings")

        if not replacements:
            logger.info("No findings to apply")
            return data

        applied = 0
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        for ch_list_idx, chapter in enumerate(chapters):
            ch_num = ch_list_idx + 1  # 1-based to match report["chapter"]
            for block in chapter.get("content_blocks", []):
                bid = block.get("id", block.get("block_id", ""))
                finding = replacements.get((ch_num, bid))
                if finding:
                    original = block.get("translated_content", "")
                    replacement = finding["replacement_translated_content"]
                    # Guard: reject replacements that truncate content
                    if original and len(replacement) < len(original) * 0.8:
                        logger.warning(
                            f"  {bid}: review replacement rejected — output "
                            f"({len(replacement)} chars) is <80% of original "
                            f"({len(original)} chars), likely truncated"
                        )
                        continue
                    block["translated_content"] = replacement
                    if finding.get("replacement_footnotes") is not None:
                        block["footnotes"] = finding["replacement_footnotes"]
                    applied += 1

        logger.info(f"Applied {applied} replacements from {len(replacements)} findings")
        return data

    def _resolve_genre_brief(self, data: dict) -> str:
        """Extract genre/style brief from PROMPT_REGISTRY based on work metadata."""
        try:
            from processors.translation_prompts import resolve_prompt_key, PROMPT_REGISTRY

            meta = data.get("meta", {})
            author_chinese = meta.get("author_chinese", "")
            category = meta.get("category_english", "")

            key = resolve_prompt_key(author_chinese, category)
            full_brief = PROMPT_REGISTRY.get(key, "")
            if full_brief:
                return _extract_genre_brief(full_brief)
        except Exception as e:
            logger.debug(f"Could not resolve genre brief: {e}")

        return "Standard wuxia literary register — formal martial arts prose with period-appropriate language."

    def _load_suppress_ideograms(self) -> Set[str]:
        """Load suppress list ideograms."""
        try:
            from processors.translation_prompts import get_suppress_ideograms
            return get_suppress_ideograms()
        except Exception as e:
            logger.debug(f"Could not load suppress list: {e}")
            return set()


# =============================================================================
# REVIEW ADJUDICATOR — second LLM pass to accept/reject review findings
# =============================================================================

_ADJUDICATOR_SYSTEM_PROMPT = """You are a translation quality adjudicator. You will be shown a review finding that proposes a change to a translated block. Your job is to decide whether the proposed change should be ACCEPTED or REJECTED.

Consider:
1. Is the identified issue REAL? (The reviewer may have flagged something that is actually correct.)
2. Is the proposed replacement an IMPROVEMENT? (Sometimes the fix introduces new problems.)
3. Does the reviewer's reasoning hold when you examine the referenced context blocks?

Be conservative — reject changes that:
- Fix a non-existent problem
- Introduce register breaks, gender errors, or meaning shifts
- Flatten vivid language into bland alternatives
- Override deliberate translator choices (calques, archaic diction, pinyin honorifics)

Accept changes that:
- Fix genuine gender pronoun errors (verified against source 他/她)
- Fix tense drift in retrospective narration
- Fix modern register in period settings
- Fix literal calques of Chinese idioms/curses that don't work in English
- Fix missing or misplaced footnote markers
- Add footnotes for character-count references (e.g. "thirteen characters" needs the Chinese breakdown)
- Fix name errors where a character's name doesn't match the Chinese source (e.g. Rénfèng rendered as Gūniáng)
- Fix martial formulae/couplets left as pinyin instead of translated to English

Return ONLY valid JSON:
{
  "accept": true or false,
  "reason": "Brief explanation (1-2 sentences)"
}"""


class ReviewAdjudicator:
    """Second-pass LLM adjudicator for consistency review findings.

    Reviews each finding individually with surrounding context and
    referenced blocks to decide accept/reject. Runs all findings
    in parallel (one request per finding, up to max_workers concurrent).

    Usage:
        adjudicator = ReviewAdjudicator(model="deepseek-chat", provider="deepseek")
        adjudicated_reports = adjudicator.adjudicate_reports(reports, data)
        # Then apply with: reviewer.apply_findings(data, adjudicated_reports, respect_accepted=True)
    """

    CONTEXT_RADIUS = 2  # include ±N blocks around the finding for context

    def __init__(self, model: str = "deepseek-chat", provider: str = "deepseek",
                 temperature: float = 0.15, max_workers: int = 50):
        self.model = model
        self.provider = provider
        self.temperature = temperature
        self.max_workers = max_workers
        self._client = None

    def _get_client(self):
        if self._client is None:
            from utils.clients.llm_config import get_llm_client
            self._client = get_llm_client(
                component="adjudicate",
                provider=self.provider,
                model=self.model,
            )
        return self._client

    def adjudicate_reports(self, reports: List[dict], data: dict) -> List[dict]:
        """Adjudicate all findings across all chapter reports.

        Args:
            reports: List of chapter reports from ConsistencyReviewer.review_work().
            data: Full work data dict (for block context lookup).

        Returns:
            The same reports list with finding["accepted"] set to True/False.
        """
        # Build block lookup: block_id -> (chapter_idx, block)
        block_lookup = self._build_block_lookup(data)
        # Build ordered block_id list per chapter for context windowing
        chapter_block_ids = self._build_chapter_block_ids(data)

        # Collect all findings that need adjudication
        tasks = []
        for report in reports:
            ch_idx = report.get("chapter", 0)
            for finding in report.get("findings", []):
                # Skip already-decided findings
                if finding.get("accepted") is not None:
                    continue
                # Skip no-text-change findings (shouldn't exist after parse, but safe)
                orig = (finding.get("original_translated_content") or "").strip()
                repl = (finding.get("replacement_translated_content") or "").strip()
                if orig == repl:
                    finding["accepted"] = False
                    finding["adjudication_reason"] = "No text change"
                    continue
                tasks.append((finding, ch_idx, block_lookup, chapter_block_ids))

        if not tasks:
            logger.info("No findings to adjudicate")
            return reports

        logger.info(f"Adjudicating {len(tasks)} findings (max_workers={self.max_workers})")

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {}
            for finding, ch_idx, bl, cbi in tasks:
                fut = pool.submit(
                    self._adjudicate_one, finding, ch_idx, bl, cbi
                )
                futures[fut] = finding

            accepted_count = 0
            rejected_count = 0
            for fut in as_completed(futures):
                finding = futures[fut]
                try:
                    accept, reason = fut.result()
                    finding["accepted"] = accept
                    finding["adjudication_reason"] = reason
                    if accept:
                        accepted_count += 1
                    else:
                        rejected_count += 1
                except Exception as e:
                    logger.error(f"Adjudication failed for {finding.get('block_id')}: {e}")
                    # Default to accept on error (don't silently drop fixes)
                    finding["accepted"] = True
                    finding["adjudication_reason"] = f"Accepted by default (adjudication error: {e})"
                    accepted_count += 1

        logger.info(f"Adjudication complete: {accepted_count} accepted, {rejected_count} rejected")
        return reports

    def _adjudicate_one(self, finding: dict, chapter_idx: int,
                        block_lookup: dict, chapter_block_ids: dict) -> tuple:
        """Adjudicate a single finding. Returns (accept: bool, reason: str)."""
        from utils.clients.llm_client import LLMRequest

        user_msg = self._build_adjudication_prompt(
            finding, chapter_idx, block_lookup, chapter_block_ids
        )

        client = self._get_client()
        response = client.chat(LLMRequest(
            messages=[
                {"role": "system", "content": _ADJUDICATOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            model=self.model,
            temperature=self.temperature,
            max_tokens=256,
            json_mode=True,
            timeout=60,
        ))

        parsed = response.parsed
        if parsed is None:
            parsed = _extract_json(response.text)

        if not parsed:
            logger.warning(f"No parsed adjudication for {finding.get('block_id')}, accepting by default")
            return True, "Accepted by default (unparseable response)"

        accept = parsed.get("accept", True)
        reason = parsed.get("reason", "No reason given")
        return bool(accept), str(reason)

    def _build_adjudication_prompt(self, finding: dict, chapter_idx: int,
                                   block_lookup: dict,
                                   chapter_block_ids: dict) -> str:
        """Build the user prompt for adjudicating one finding."""
        block_id = finding["block_id"]
        parts = [
            f"## Finding for {block_id} (Chapter {chapter_idx})",
            f"**Category:** {finding.get('category', '?')}",
            f"**Severity:** {finding.get('severity', '?')}",
            f"**Reviewer's note:** {finding.get('note', 'None')}",
            "",
            "### Original block:",
            f"```",
            finding.get("original_translated_content", "(not available)"),
            f"```",
            "",
            "### Proposed replacement:",
            f"```",
            finding.get("replacement_translated_content", "(not available)"),
            f"```",
        ]

        # Add source text if available
        block_key = (chapter_idx, block_id)
        if block_key in block_lookup:
            block = block_lookup[block_key]
            source = block.get("source_content") or block.get("content") or ""
            if source:
                parts.extend([
                    "",
                    "### Source Chinese:",
                    f"```",
                    source[:1000],
                    f"```",
                ])

        # Add surrounding context blocks
        context_blocks = self._get_context_blocks(
            block_id, chapter_idx, block_lookup, chapter_block_ids
        )
        if context_blocks:
            parts.extend(["", "### Surrounding context:"])
            for ctx_id, ctx_trans in context_blocks:
                marker = " ← THIS BLOCK" if ctx_id == block_id else ""
                parts.append(f"[{ctx_id}]{marker}: {ctx_trans[:300]}...")

        # Parse referenced block_ids from the reviewer's note
        referenced = self._extract_referenced_blocks(finding.get("note", ""), block_lookup, chapter_idx)
        if referenced:
            parts.extend(["", "### Referenced blocks (from reviewer's note):"])
            for ref_id, ref_block in referenced:
                ref_trans = ref_block.get("translated_content", "")
                ref_src = ref_block.get("source_content") or ref_block.get("content") or ""
                parts.append(f"[{ref_id}] EN: {ref_trans[:300]}")
                if ref_src:
                    parts.append(f"[{ref_id}] ZH: {ref_src[:200]}")

        parts.extend(["", "Should this change be accepted or rejected?"])
        return "\n".join(parts)

    def _get_context_blocks(self, block_id: str, chapter_idx: int,
                            block_lookup: dict, chapter_block_ids: dict) -> list:
        """Get ±CONTEXT_RADIUS blocks around the finding."""
        ordered = chapter_block_ids.get(chapter_idx, [])
        if not ordered or block_id not in ordered:
            return []

        idx = ordered.index(block_id)
        start = max(0, idx - self.CONTEXT_RADIUS)
        end = min(len(ordered), idx + self.CONTEXT_RADIUS + 1)

        result = []
        for i in range(start, end):
            ctx_id = ordered[i]
            ctx_key = (chapter_idx, ctx_id)
            if ctx_key in block_lookup:
                blk = block_lookup[ctx_key]
                trans = blk.get("translated_content", "")
                if trans:
                    result.append((ctx_id, trans))
        return result

    def _extract_referenced_blocks(self, note: str, block_lookup: dict,
                                    chapter_idx: int = None) -> list:
        """Parse block_id references from reviewer's note text.

        Searches the finding's own chapter first, then falls back to all chapters.
        """
        if not note:
            return []
        matches = re.findall(r'block_\d+', note)
        result = []
        seen = set()
        for ref_id in matches:
            if ref_id in seen:
                continue
            seen.add(ref_id)
            # Try same chapter first
            if chapter_idx and (chapter_idx, ref_id) in block_lookup:
                result.append((ref_id, block_lookup[(chapter_idx, ref_id)]))
            else:
                # Search all chapters
                for key, block in block_lookup.items():
                    if key[1] == ref_id:
                        result.append((ref_id, block))
                        break
        return result

    def _build_block_lookup(self, data: dict) -> dict:
        """Build (chapter_idx, block_id) -> block mapping.

        Keyed by (ch_idx, bid) to prevent collisions when block IDs
        restart per chapter (e.g. block_0003 in ch1 and ch2).
        """
        lookup = {}
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        for ch_idx, chapter in enumerate(chapters, 1):
            for block in chapter.get("content_blocks", []):
                bid = block.get("id", block.get("block_id", ""))
                if bid:
                    lookup[(ch_idx, bid)] = block
        return lookup

    def _build_chapter_block_ids(self, data: dict) -> dict:
        """Build chapter_idx -> ordered list of block_ids."""
        result = {}
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        for ch_idx, chapter in enumerate(chapters, 1):
            ids = []
            for block in chapter.get("content_blocks", []):
                bid = block.get("id", block.get("block_id", ""))
                if bid:
                    ids.append(bid)
            result[ch_idx] = ids
        return result
