# Translation-to-EPUB Workflow

Complete pipeline: **Cleaned JSON → Translate → Footnote Cleanup → Pinyin Injection → EPUB**

---

## Pipeline Overview

```
Cleaned JSON (8-stage batch pipeline output)
    │
    ├── Stage 1: METADATA translation (no footnotes)
    ├── Stage 2: TOC translation (no footnotes)
    ├── Stage 3: HEADINGS translation (no footnotes)
    ├── Stage 4: BODY translation (WITH footnotes, parallel)
    ├── Stage 5: SPECIAL SECTIONS translation (WITH footnotes)
    ├── Stage 6: FOOTNOTE CLEANUP (4-phase, 93-98% reduction)
    ├── Stage 7: VALIDATION (completeness + quality)
    │
    ├── Post: Pinyin footnote injection (first-occurrence honorifics)
    │
    └── EPUB generation (EPUB3 with popup footnotes, series metadata)
```

**Orchestrator**: `scripts/orchestrate_translation_pipeline.py`
**Usage**:
```bash
python scripts/orchestrate_translation_pipeline.py D1379
python scripts/orchestrate_translation_pipeline.py D1379 --volume a
python scripts/orchestrate_translation_pipeline.py D1379 --resume
python scripts/orchestrate_translation_pipeline.py D1379 --start-stage 4 --end-stage 6
```

---

## Stage 1-3: Metadata, TOC & Headings Translation

**No footnotes** — clean metadata only.

| Stage | What | Output |
|-------|------|--------|
| 1 METADATA | Title, author, publisher | English meta block |
| 2 TOC | Table of contents entries | English chapter list |
| 3 HEADINGS | Chapter titles | English headings |

These stages use the same translation model but with prompts that explicitly suppress footnote generation.

---

## Stage 4: Body Translation

**File**: `processors/translator.py` + `wrappers/content_block_translation_wrapper_v2.py`

### Translation Flow (per content block)

```
Source block (Classical Chinese)
    │
    ├── 1. Scan for glossary terms (utils/glossary_context_builder.py)
    ├── 2. Check accumulator for already-footnoted terms
    ├── 3. Build V2 system prompt with:
    │      • Suppress list (100+ common wuxia terms)
    │      • Already-footnoted context (cross-block dedup)
    │      • Glossary context (dedup-aware)
    │
    ├── 4. API call: Chat Completions (gpt-4.1-nano, temp 0.3)
    │      → Returns: annotated_content_text + content_footnotes
    │
    ├── 5. Validation pass (second API call)
    │      → Checks accuracy, pinyin, marker format
    │      → Retry on critical issues
    │
    ├── 6. Filter footnotes (remove suppressed + already-seen)
    ├── 7. Register surviving ideograms in accumulator
    │
    └── Output: translated block with [1][2] markers + footnotes
```

### V2 Translation Prompts

**File**: `processors/translation_prompts_v2.py`

Key style rules:
- **Literary register**: formal jianghu dialogue (討教 → "seek instruction", not "want to learn")
- **Character names**: ALWAYS pinyin with tone marks (Yún Lěi, NOT "Cloud Lei")
- **Martial terms**: precise translations (紫金刀 → "Purple-Gold Sabre", 判官筆 → "Judge's Brush")
- **Italicized pinyin**: untranslated terms in *italics* (e.g., *qìnggōng*, *jiānghú*)
- **Footnote density**: 2-3 max per block; zero is often best

Footnote rules:
- **DO footnote**: real historical figures, named martial techniques, cultural/religious practices, first-occurrence honorifics
- **NEVER footnote**: fictional character names, common nouns, emotions, anything clear in English

### Cross-Block Deduplication

**File**: `utils/footnote_context.py` — `FootnoteContextAccumulator`

- Thread-safe tracker of all footnoted ideograms across the entire work
- Each block queries the accumulator before translation → prompt includes "already explained" terms
- Prevents the translator from re-explaining 氣 (qì) in every chapter

### Glossary Context

**File**: `utils/glossary_context_builder.py`

Per-term deduplication strategies:
- **FIRST_OCCURRENCE_ONLY**: Full footnote if new, suppress if already seen
- **RECURRING_BRIEF**: Full if new, brief reminder (pinyin + 3-5 words) if recurring
- **EVERY_OCCURRENCE**: Always full footnote regardless

### Suppress List

**File**: `config/suppress_list.json`

100+ common wuxia terms the translator should NOT footnote because readers already know them:
```json
{"chinese": "江湖", "pinyin": "jiānghú", "english": "the jianghu / martial world"},
{"chinese": "氣", "pinyin": "qì", "english": "qi / vital energy"},
{"chinese": "內功", "pinyin": "nèigōng", "english": "internal martial arts / neigong"}
```

Injected directly into V2 system prompt so the model sees the full list.

### Translation Output Format

```json
{
  "annotated_content_text": "Hú Yīdāo stood at the cliff edge, his *qì* surging through his *jīngmài*[1]...",
  "content_footnotes": [
    {
      "footnote_key": 1,
      "footnote_details": {
        "footnote_ideogram": "經脈",
        "footnote_pinyin": "jīngmài",
        "footnote_explanation": "Meridian channels — the network of pathways..."
      }
    }
  ],
  "content_type": "narrative"
}
```

---

## Stage 5: Special Sections

Same translation logic as Stage 4, applied to front_matter and back_matter (prefaces, afterwords, appendices). Footnotes are generated for cultural content.

---

## Stage 6: Footnote Cleanup (4-Phase Pipeline)

**File**: `utils/remove_trivial_footnotes.py` — `TrivialFootnoteRemover`

The raw translator output contains far too many footnotes. This 4-phase pipeline removes 93-98% while preserving genuinely valuable cultural/historical content.

### Phase 1: Suppress List (programmatic, instant)

- Match footnote ideograms against `config/suppress_list.json`
- Remove footnotes with empty explanations
- Typical: ~10-40 removed per chapter

### Phase 1.5: Heuristic Patterns (programmatic, instant)

Pattern-based detection of trivial categories:

| Category | Pattern | Example |
|----------|---------|---------|
| CHAR_NAME | "A personal name", "A character's name" | 胡一刀 → "A character name" |
| FREQ_NAME | 2-3 char ideograms appearing 3+ times | Fictional names repeated throughout |
| TRIVIAL_ACTION | Emotions, gestures, actions | "sighing", "shaking head" |
| SHORT_NO_CULTURE | Explanation < 80 chars, no cultural signals | Simple word translations |

**Cultural signal regex** prevents false positives: dynasty names, emperor references, Buddhist/Taoist terms, martial technique names, etc.

Typical: ~130-250 removed per chapter.

### Phase 2: AI Scoring — In-Context (GPT-4.1-nano)

- Scores remaining footnotes WITH paragraph context
- Two axes: `triviality` (0-100) + `cultural_specificity` (0-100)
- Removal rules:
  - `triviality ≥ 80` removes **unless** `cultural_specificity ≥ 80` AND model says keep
  - `should_remove=True` AND `triviality ≥ 50` → remove
- Also performs work-wide deduplication by ideogram (first occurrence only)
- Batch size: 25 footnotes per API call
- Typical: ~30-50 removed per chapter

### Phase 3: AI Review — Context-Free by Ideogram (GPT-4.1-nano)

**The breakthrough phase.**

- Collects unique ideogram→explanation pairs across the **entire work**
- Sends ONLY ideogram + explanation (no surrounding paragraph)
- Stricter prompt: "Does this add genuine cultural knowledge?"
- Without narrative context, the model is harsher on vague/trivial explanations
- Removes ALL occurrences of flagged ideograms across all blocks
- Temperature: 0.1 (very consistent)
- Typical: ~60-95 removed per chapter

### Example Results

D440 七劍下天山, Chapter 3 (359 raw footnotes):

| Phase | Removed | Remaining |
|-------|---------|-----------|
| Start | — | 359 |
| Phase 1 (suppress) | -38 | 321 |
| Phase 1.5 (heuristics) | -201 | 120 |
| Phase 2 (AI in-context) | -33 | 87 |
| Phase 3 (AI context-free) | -68 | **26** |

**93% removed.** All 26 survivors: genuine cultural/historical content (Kangxi Emperor, Wudang, Dalai Lama, Zhuangzi, etc.)

### Post-Cleanup Operations

After all 4 phases:
- Footnote renumbering (sequential per chapter)
- Marker repositioning (outside quotes, word-boundary aware)
- Orphan marker removal (markers with no matching footnote)
- Chapter-continuous renumbering

---

## Stage 7: Validation

- Verify all blocks have translations
- Check footnote marker integrity ([N] markers match footnote entries)
- Quality scoring
- Generate validation report

---

## Post-Translation: Pinyin Footnote Injection

**File**: `utils/inject_pinyin_footnotes.py`

After cleanup removes most footnotes, some italicized pinyin terms (*shīmèi*, *qīnggōng*, *jiānghú*) are left without explanation. This step adds first-occurrence footnotes for those terms.

### Logic

```
1. Scan all translated text for italicized pinyin: *qì*, *shīmèi*, etc.
2. Check which ones already have footnotes somewhere in the work
3. For unfootnoted terms, look up definition from:
   • config/suppress_list.json
   • Built-in glossary (150+ wuxia terms in _BUILTIN_GLOSSARY)
4. Inject footnote at FIRST occurrence only
5. Apply insertions in reverse order (maintains valid string positions)
```

### Built-in Glossary

150+ wuxia terms with chinese/pinyin/english definitions:
- Honorifics: 師兄 (shīxiōng), 師妹 (shīmèi), 長老 (zhǎnglǎo), 掌門 (zhǎngmén)
- Martial terms: 刀法 (dāofǎ), 劍法 (jiànfǎ), 輕功 (qīnggōng), 氣 (qì)
- Cultural: 江湖 (jiānghú), 武林 (wǔlín), 恩怨 (ēnyuàn)

### Protection Mechanism

The cleanup pipeline (Stage 6) has a protection mechanism for terms that will need pinyin footnotes:
- Phase 0 builds a set of protected ideograms (matching italicized pinyin in text)
- All 4 phases skip protected ideograms on first occurrence
- Prevents cleanup from removing footnotes that injection would re-add

---

## EPUB Generation

**File**: `processors/epub_builder_v2.py` — `EpubBuilderV2`

**Usage**:
```bash
python processors/epub_builder_v2.py input.json                    # Auto-named output
python processors/epub_builder_v2.py input.json --output book.epub # Explicit output
```

### Features

| Feature | Detail |
|---------|--------|
| **EPUB3** | Full EPUB3 compliance with NCX fallback |
| **Popup footnotes** | `epub:type="noteref"` / `epub:type="footnote"` for reader popups |
| **Kindle-compatible** | Uses `<div epub:type="footnote">` (visible + popup; `<aside>` is hidden on Kindle) |
| **Bidirectional links** | Click footnote number → jump to footnote; click back-arrow → return to text |
| **Content-type formatting** | Different CSS classes for narrative, dialogue, verse, document, thought, descriptive |
| **Series metadata** | Queries SQLite catalog for series name + order; shown on title page and in filename |
| **English chapter headings** | 第N回/章 → "Chapter N" with Chinese numeral parser (handles 廿卅卌) |
| **Bilingual title page** | English title + Chinese title, series info, author (both languages) |
| **Auto filename** | `Author - Title (Series #NN).epub` |

### Footnote HTML Structure

In chapter body:
```html
<a epub:type="noteref" id="fnref-ch3-7" href="#fn-ch3-7">[7]</a>
```

At chapter end:
```html
<section class="chapter-footnotes">
  <h3>Footnotes</h3>
  <div epub:type="footnote" id="fn-ch3-7" class="footnote-entry">
    <p><a href="#fnref-ch3-7" class="fn-number">[7]</a>
    <strong>經脈</strong> (jīngmài) — Meridian channels — the network of pathways...</p>
  </div>
</section>
```

### Content-Type Formatting

```html
<!-- narrative -->
<p class="narrative">He drew his sword slowly...</p>

<!-- dialogue -->
<p class="dialogue">"You dare challenge me?" Hú Yīdāo said coldly.</p>

<!-- verse -->
<div class="verse">
  <p class="verse-line">The autumn wind sweeps across the mountain pass,</p>
  <p class="verse-line">A lone swordsman walks beneath the fading moon.</p>
</div>

<!-- document/letter -->
<blockquote class="document">To the heroes of the Central Plains...</blockquote>

<!-- thought -->
<p class="thought">If I strike now, he thought, there will be no turning back.</p>
```

### Chapter Title Translation

`_translate_chapter_title()` with `_parse_chinese_num()`:

| Chinese | English |
|---------|---------|
| 第一回 雪山飛狐 | Chapter 1: The Flying Fox of Snowy Mountain |
| 第廿一章 | Chapter 21 |
| 第卅二回 | Chapter 32 |
| 回目 (no number) | Kept as-is |

### Series Lookup

Queries SQLite catalog (`works_translator.duckdb`):
```
works.work_number → work_series.series_id → series.name, order_in_series, total_in_series
```

Result in title page: **Fox Volant Duology — Book 01 of 02**
Result in filename: `Jin Yong - The Flying Fox of Snowy Mountain (Fox Volant Duology #01).epub`

---

## WIP & Checkpoint Structure

Each stage saves work-in-progress files for resumability:

```
/Users/jacki/project_files/translation_project/
├── cleaned/COMPLETE_ALL_BOOKS/     ← Input (cleaned JSON)
├── wip/
│   ├── stage_1_metadata/
│   ├── stage_2_toc/
│   ├── stage_3_headings/
│   ├── stage_4_body/               ← Largest stage, per-chapter checkpoints
│   ├── stage_5_special/
│   ├── stage_6_cleanup/
│   └── stage_7_validation/
├── translated_files/               ← Final output
└── translation_data/logs/
    ├── D1379_translation.log
    ├── D1379_stage_N_*.json        ← Per-stage logs
    └── checkpoints/
        └── D1379_checkpoint.json   ← Resume point
```

`--resume` flag picks up from the last completed stage.

---

## Configuration Summary

| Setting | Value | Where |
|---------|-------|-------|
| Translation model | gpt-4.1-nano | translator.py, translation_prompts_v2.py |
| Translation temperature | 0.3 | translator.py |
| Validation temperature | 0.1 | translator.py |
| Cleanup scoring temp | 0.1 | remove_trivial_footnotes.py |
| Max retries | 2-3 | translator.py, wrapper |
| API timeout | 120s | translator.py |
| Cleanup batch size | 25 | remove_trivial_footnotes.py |
| Max parallel chapters | 3-5 | orchestrator config |
| Suppress list | 100+ terms | config/suppress_list.json |
| Built-in glossary | 150+ terms | inject_pinyin_footnotes.py |

---

## Key Files

| File | Purpose |
|------|---------|
| `scripts/orchestrate_translation_pipeline.py` | 7-stage pipeline orchestrator |
| `processors/translator.py` | Core translation service (two-pass) |
| `processors/translation_prompts_v2.py` | V2 prompts (literary register, suppress list) |
| `wrappers/content_block_translation_wrapper_v2.py` | V2 translation wrapper with dedup |
| `utils/footnote_context.py` | Cross-block footnote accumulator |
| `utils/glossary_context_builder.py` | Dedup-aware glossary context |
| `utils/remove_trivial_footnotes.py` | 4-phase footnote cleanup |
| `utils/inject_pinyin_footnotes.py` | First-occurrence pinyin injection |
| `processors/epub_builder_v2.py` | EPUB3 generation |
| `config/suppress_list.json` | Suppress list (100+ terms) |
| `styles/kindle.css` | EPUB CSS stylesheet |
