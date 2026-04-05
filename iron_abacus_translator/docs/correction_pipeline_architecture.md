# Iron Abacus — Correction & Review Pipeline Architecture

## Overview

The correction and review pipeline runs **after translation and footnote cleanup**, ensuring translation quality through a layered system of programmatic checks, LLM-based classification, focused correction, consistency review, and adjudication. It operates on the full work (all chapters) before EPUB generation.

```
translated work (post-cleanup)
    ↓
┌─────────────────────────────────────────────────────┐
│  validation — coverage check, footnote integrity     │
└──────────────────────┬──────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│  review — per-chapter consistency review (LLM)       │
│    14 review categories, windowed context             │
└──────────────────────┬──────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│  review_adjudicate — accept/reject each finding      │
│    LLM adjudicator + 80% length guard                │
└──────────────────────┬──────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│  correction_classify — programmatic pre-pass (14     │
│    regex/logic checks) + LLM triage (DeepSeek)       │
└──────────────────────┬──────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│  correction_apply — focused LLM corrections +        │
│    6-step post-processing pipeline                   │
└──────────────────────┬──────────────────────────────┘
                       ↓
                  epub_build
```

## Pipeline Stages (DAG order)

| # | Node | Type | File | Purpose |
|---|------|------|------|---------|
| 1 | `validation` | Programmatic | `pipeline_runner.py` | Coverage %, footnote integrity check |
| 2 | `review` | LLM (DeepSeek) | `consistency_reviewer.py` | Per-chapter consistency review |
| 3 | `review_adjudicate` | LLM (DeepSeek) | `consistency_reviewer.py` | Accept/reject review findings |
| 4 | `correction_classify` | Programmatic + LLM | `correction_classifier.py` | Tag blocks with issue categories |
| 5 | `correction_apply` | LLM + Programmatic | `correction_applicator.py` | Fix tagged issues, post-process |
| 6 | `epub_build` | Programmatic | `crimson_folio/` | Generate EPUB from corrected JSON |

---

## Stage 2: Consistency Review

**File**: `processors/consistency_reviewer.py`
**Model**: DeepSeek (deepseek-chat), temperature 0.15
**Parallelism**: 5 workers (one per chapter window, ~25 blocks per window)

### Review Categories

The reviewer examines each chapter in sliding windows and tags findings by category:

| Category | Severity | What it catches |
|----------|----------|-----------------|
| `tense` | error/warning | Past/present mixing, tense drift in retrospective narration |
| `gender` | error | He/she/his/her pronoun confusion vs Chinese source (他/她/它) |
| `name` | error | Character name doesn't match Chinese source (e.g. Rénfèng → Gūniáng) |
| `style` | warning | Anachronistic phrasing, mistranslation, paratactic chains |
| `register` | error | Modern English in jiānghú context ("heist", "gang", "Messrs.") |
| `honorific` | error | English translations where pinyin expected (*Shīxiōng* not "Senior Brother") |
| `formula_pinyin` | error | Martial formulae/couplets left as pinyin instead of translated |
| `weapon` | error | "long sword" for 長劍, weapon type mismatches |
| `idiom` | warning | Literal calques of Chinese curses/idioms |
| `footnote` | info/error | Missing footnotes on culturally significant terms |
| `char_count` | error | "N characters" reference without footnote giving Chinese breakdown |
| `pinyin` | error | Missing tone marks, incorrect romanization |
| `date` | error | Incorrect reign year → CE conversion in footnotes |

### Review Prompt Structure

The system prompt is built dynamically with numbered sections:

```
1.   tense — rules for legitimate vs erroneous tense shifts
1b.  name accuracy — cross-check names against Chinese source
2.   gender — pronoun verification against 他/她/它
3.   style — register, anachronism, mistranslation
3a.  register — modern crime slang, corporate English
3b.  honorific — pinyin vs English, translated surnames
3b2. formula_pinyin — martial formulae must be translated
3c.  weapon — long sword, weapon tracking, technique verbs
3d.  idiom — literal calque fixes
4.   footnote — culturally significant terms, consolidated
4b.  char_count — character-count references need breakdown
5.   pinyin — tone diacritics on all pinyin
6.   date — reign year → CE conversion
```

Each finding produces:
```json
{
  "block_id": "block_NNNN",
  "category": "name",
  "severity": "error",
  "note": "Brief explanation",
  "original_translated_content": "...",
  "replacement_translated_content": "...",
  "replacement_footnotes": [...]
}
```

---

## Stage 3: Review Adjudication

**File**: `processors/consistency_reviewer.py` → `ReviewAdjudicator`
**Model**: DeepSeek (deepseek-chat), temperature 0.15
**Parallelism**: 50 workers (one per finding)

### Adjudicator Prompt

The adjudicator reviews each finding independently with ±2 blocks of surrounding context.

**Accept** changes that:
- Fix genuine gender pronoun errors (verified against source 他/她)
- Fix tense drift in retrospective narration
- Fix modern register in period settings
- Fix literal calques of Chinese idioms/curses
- Fix missing or misplaced footnote markers
- Add footnotes for character-count references
- Fix name errors (e.g. Rénfèng rendered as Gūniáng)
- Fix martial formulae/couplets left as pinyin

**Reject** changes that:
- Fix a non-existent problem
- Introduce register breaks, gender errors, or meaning shifts
- Flatten vivid language into bland alternatives
- Override deliberate translator choices

### Length Guard

When applying accepted findings, a **80% length guard** rejects replacements that truncate content:
```python
if len(replacement) < len(original) * 0.8:
    logger.warning(f"review replacement rejected — likely truncated")
```

---

## Stage 4: Correction Classification

**File**: `processors/correction_classifier.py`
**Two phases**: programmatic pre-pass (instant) → LLM classification (parallel)

### Phase 1: Programmatic Pre-Pass (14 checks)

All checks run before any LLM call. Each fires a regex or logic test and auto-tags the block.

| # | Tag | Detector | What it catches |
|---|-----|----------|-----------------|
| 1 | `ideogram_leak` | `_find_cjk_in_translation()` | CJK characters in English body text |
| 2 | `char_count` | `_has_character_count_ref()` | "N characters" without nearby footnote marker |
| 3 | `weapon` | `_has_long_sword()` | "long sword(s)" in body text |
| 4 | `bare_pinyin` | `_has_bare_pinyin()` | Common pinyin without tone diacritics (Shifu → Shīfù) |
| 5 | `pinyin_sequence` | `_has_unitalicized_pinyin_sequence()` | Repeated syllables not in *asterisks* (peng peng peng) |
| 6 | `unitalicized_honorific` | `_has_unitalicized_honorific()` | Honorific pinyin with tones but no *italics* |
| 7 | `suppressed_footnote` | `_has_suppressed_footnote()` | Footnote ideogram on suppress list |
| 8 | `omission` | `_is_omission()` | English < 80% of Chinese source length |
| 9 | `duplicate_text` | `_has_duplicate_text()` | Repeated 40+ char phrases (LLM stutter) |
| 10 | `orphan_marker` | `_has_orphan_marker()` | Marker [N] with no footnote entry, or vice versa |
| 11 | `western_units` | `_has_western_units()` | feet/miles/pounds where Chinese units expected |
| 12 | `gang_not_clan` | `_has_gang_not_clan()` | "X Gang" for 幫 organizations |
| 13 | `empty_footnote` | `_has_empty_footnote()` | Footnotes with blank or <10 char explanation |
| 14 | `double_space` | `_has_double_space()` | Double spaces in body text |

**Details on key detectors**:

- **`_has_bare_pinyin()`**: Matches against a lookup table of 30+ common terms (Shifu, Guniang, Bangzhu, Jianghu, Wulin, etc.) using word-boundary regex.

- **`_has_unitalicized_pinyin_sequence()`**: Regex `(?<!\*)\b([A-Za-z]{1,6})\s+\1(?:\s+\1)*\b(?!\*)` catches repeated syllables not wrapped in asterisks. Excludes common English repeated words (the, and, had, etc.).

- **`_has_western_units()`**: Matches "N feet/miles/pounds" patterns. Excludes idiomatic "feet" usage ("rose to his feet", "at her feet", "stamped his feet") via a false-positive filter.

- **`_has_character_count_ref()`**: Matches number words + "characters/ideograms" (e.g. "thirteen characters", "3 ideograms"). Restricted to explicit numeric counts — excludes "the words", "his words", etc.

### Phase 2: LLM Classification (DeepSeek)

**Model**: DeepSeek (deepseek-chat), temperature 0.1
**Parallelism**: 25-50 workers
**Max tokens**: 128 (classification only, no correction)

The classifier prompt defines these LLM-detected categories (some overlap with programmatic for redundancy):

| Category | What the LLM looks for |
|----------|----------------------|
| `measurement` | Western units where Chinese units expected; unitalicized measurement pinyin |
| `weapon` | "long sword", weapon type mismatches, domestic "cudgel" |
| `register` | Modern/casual English in jiānghú period setting |
| `footnote_placement` | Markers on wrong words, inline glosses |
| `footnote_consolidation` | Adjacent footnotes on related terms |
| `footnote_missing` | Missing acupoint, sect, allusion, weapon footnotes; "fictional" in footnotes |
| `honorific` | English translations where pinyin expected; unitalicized honorifics |
| `idiom_curse` | Literal calques of Chinese curses/idioms |
| `technique_name` | Comical verbs in technique names; combat direction errors |
| `formula_pinyin` | Martial formulae left as pinyin |
| `char_count` | Character-count references without footnote |

**Tag merging**: Programmatic tags are merged with LLM tags. If the LLM returns `["clean"]` but programmatic checks found issues, the programmatic tags prevail.

---

## Stage 5: Correction Application

**File**: `processors/correction_applicator.py`
**Model**: DeepSeek (deepseek-chat), temperature 0.2
**Parallelism**: 50 workers

### LLM Correction

Each tagged block is sent to DeepSeek with a **focused prompt** built from only the relevant specialist rules. The prompt is assembled by `build_correction_prompt(tags)` which concatenates only the correction prompts matching the block's tags.

**26 specialist correction prompts** cover:

| Prompt key | Summary |
|-----------|---------|
| `measurement` | Convert Western → Chinese units as italicized pinyin |
| `weapon` | "long sword" → "sword"; weapon type tracking |
| `register` | Replace modern English with period alternatives |
| `footnote_placement` | Move markers to correct words |
| `footnote_consolidation` | Merge overlapping footnotes |
| `footnote_missing` | Add mandatory footnotes (acupoints, sects, allusions, character counts, reign dates) |
| `honorific` | Add pinyin honorifics with asterisks |
| `idiom_curse` | Translate Chinese curses/idioms by meaning |
| `supernatural` | Replace European creatures with Chinese equivalents |
| `technique_name` | Fix verb choices in technique names; martial formulae translated |
| `organ_metaphor` | Translate body-organ metaphors by meaning + footnote |
| `ideogram_leak` | Remove/translate CJK characters from body text |
| `formula_pinyin` | Translate martial formulae from pinyin to English |
| `char_count` | Add footnote with Chinese ideogram breakdown |
| `bare_pinyin` | Add tone diacritics to bare pinyin |
| `pinyin_sequence` | Italicize and add tones to repeated sound effects |
| `suppressed_footnote` | Remove footnote on suppressed term |
| `omission` | Translate missing content from Chinese source |
| `duplicate_text` | Remove repeated phrases |
| `unitalicized_honorific` | Add *asterisks* around honorific pinyin |
| `orphan_marker` | Remove mismatched markers/footnotes |
| `western_units` | Convert Western → Chinese measurement units |
| `gang_not_clan` | "Gang" → "Clan" for 幫 organizations |

**Tags handled without LLM** (programmatic cleanup only):
- `double_space` — regex replacement
- `empty_footnote` — remove entries with <10 char explanation
- `orphan_marker` — remove markers with no matching footnote

### Correction System Template

The LLM receives a system prompt with:

1. **Anti-truncation rule**: "You MUST return the COMPLETE text. Every sentence must be present. Dropping sentences is a critical failure."
2. **Format rule**: Footnote markers as `[N]`, never HTML `<sup>`
3. **Specialist rules**: Only the rules matching the block's tags
4. **Footnote rules**: Never rewrite existing explanations; only add/remove
5. **Output format**: JSON with `corrected_text`, `corrected_footnotes`, `changes_made`

### Length Guard

```python
if len(corrected_text) < len(original_text) * 0.8:
    # Reject — LLM truncated the translation
    logger.warning(f"correction rejected — output is <80% of original")
```

Applied in two places:
- `correct_work()` — after LLM correction
- `_verify_marker_placement()` — after marker repositioning

### Post-Correction Pipeline (6 steps)

After LLM corrections are applied, six programmatic steps run in sequence:

| # | Method | What it does |
|---|--------|-------------|
| 1 | `_relocate_footnotes()` | Move footnotes to blocks containing their ideogram in source text |
| 2 | `_dedup_footnotes()` | Keep first occurrence of each ideogram; strip suppress-list footnotes |
| 3 | `_strip_bad_footnotes()` | LLM sweep: remove fictional, meta, trivial footnotes (50 parallel workers) |
| 4 | `_verify_marker_placement()` | LLM: verify each [N] is on the correct word (50 parallel workers) |
| 5 | `_finalize_footnotes()` | Programmatic: fix punctuation, dedup markers, renumber continuously per chapter, strip orphans |
| 6 | `_programmatic_cleanup()` | Programmatic: remove double spaces, empty footnotes, orphan markers |

---

## Data Flow Summary

```
Block in chapter
    │
    ├── [Review] LLM examines chapter windows → findings
    │       ↓
    ├── [Adjudicate] LLM accepts/rejects each finding
    │       ↓ (80% length guard on apply)
    │   Accepted findings applied to blocks
    │
    ├── [Classify — Programmatic] 14 regex/logic checks → auto-tags
    │       ↓
    ├── [Classify — LLM] DeepSeek tags remaining issues
    │       ↓ (tags merged)
    │   Block has _correction_tags = ["measurement", "weapon", ...]
    │
    ├── [Correct — LLM] Focused prompt from specialist rules
    │       ↓ (80% length guard)
    │   corrected_text applied to block
    │
    ├── [Post-process] 6-step pipeline:
    │   1. Relocate footnotes to correct blocks
    │   2. Dedup footnotes (first occurrence only)
    │   3. Strip bad footnotes (LLM sweep)
    │   4. Verify marker placement (LLM)
    │   5. Finalize: punctuation, renumber, orphans
    │   6. Cleanup: double spaces, empty footnotes
    │
    ↓
Block ready for EPUB
```

## Configuration

| Parameter | Default | Where |
|-----------|---------|-------|
| Classification model | deepseek-chat | `CorrectionClassifier.__init__()` |
| Classification temperature | 0.1 | `CorrectionClassifier.__init__()` |
| Classification max_tokens | 128 | `_classify_one()` |
| Correction model | deepseek-chat | `CorrectionApplicator.__init__()` |
| Correction temperature | 0.2 | `CorrectionApplicator.__init__()` |
| Correction max_tokens | 4096 | `_correct_one()` |
| Review temperature | 0.15 | `ConsistencyReviewer.__init__()` |
| Adjudicator temperature | 0.15 | `ReviewAdjudicator.__init__()` |
| Max workers (all stages) | 50 | `ThreadPoolExecutor` |
| Length guard threshold | 80% | `correct_work()`, `_verify_marker_placement()`, `apply_findings()` |
| Duplicate text min length | 40 chars | `_has_duplicate_text()` |
| Empty footnote threshold | 10 chars | `_has_empty_footnote()`, `_programmatic_cleanup()` |
| Omission threshold | 80% of source | `_is_omission()` |

## Files

| File | Role |
|------|------|
| `processors/correction_classifier.py` | Programmatic checks + LLM classification |
| `processors/correction_prompts.py` | Category definitions + 26 specialist prompts + system template |
| `processors/correction_applicator.py` | LLM correction + 6-step post-processing |
| `processors/consistency_reviewer.py` | Review + adjudication + finding application |
| `config/suppress_list.json` | 100+ suppressed footnote terms |
| `scripts/pipeline_runner.py` | DAG execution, stage registration |
| `workflows/translation_pipeline_dag.py` | DAG node definitions and dependencies |
