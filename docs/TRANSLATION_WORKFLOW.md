# Translation-to-EPUB Workflow

Complete reference for translating Classical Chinese wuxia novels into English with cultural footnotes and generating Kindle-ready EPUBs.

## Pipeline Overview

```
Cleaned JSON
    |
    v
[1] Translate metadata (title, author)        ── no footnotes
[2] Translate chapter titles                   ── no footnotes
[3] Translate body blocks                      ── with footnotes + suppress list + dedup
    |
    v
[4] 4-phase footnote cleanup                  ── suppress → heuristics → AI scoring → AI review
    |
    v
[5] Marker repositioning + AI verification    ── ensure [N] sits next to its term
[6] Renumber + orphan sanitization            ── chapter-continuous keys, strip orphans
[7] Validation                                ── structural integrity + quality scoring
    |
    v
[8] EPUB generation                           ── popup footnotes, dialogue splitting, Kindle CSS
```

---

## Stage 1–3: Translation

### Entry Points

| Script | Use case |
|--------|----------|
| `scripts/translate_chapters_limit.py` | Ad-hoc: translate N chapters with full pipeline |
| `scripts/orchestrate_translation_pipeline.py` | Production: 7-stage pipeline with checkpoint/resume |

### Translation Prompts (`processors/translation_prompts.py`)

#### Absolute Rules

1. **Zero Chinese ideograms in output.** Translate everything — weapons, techniques, honorifics, place names.
2. **Character names → pinyin with tone marks, never translated.**
   `雲蕾 → Yún Lěi` (not "Cloud Lei", not "Yun Lei").
3. **Footnote only what genuinely needs explanation. Zero is often best.**
4. **First occurrence only.** Never re-footnote a term already explained.

#### What Gets Footnoted

| Footnote | Don't Footnote |
|----------|---------------|
| Real historical figures, events, reign titles | Fictional character names |
| Named martial arts techniques and schools | Common nouns, emotions, actions |
| Cultural/religious practices unknown to Western readers | Anything the English already conveys |
| Acupoints, meridians, pressure points | Any term on the suppress list (114 terms) |
| Honorifics (*Shīxiōng*, *Dàgē*, *Shīfu*) | |

#### Literary Register

- Oxford World's Classics / Penguin Classics standard
- 討教 → formal challenge to duel, not "want to learn"
- 暗放冷箭 → "firing cold arrows from the shadows", not "sneaky shots"
- Simple past tense consistently; pluperfect only when sequence requires it
- Vary sentence length for rhythm; break long Chinese sentences into well-shaped English

#### Martial Arts Translation

| Chinese | English |
|---------|---------|
| Technique names | English translation, capitalized: "Whirlwind Palm" |
| Weapon types | English: 劍 sword, 刀 sabre, 鞭 whip |
| Internal energy | 內勁 → "internal force"; 氣 → "qi" / "vital energy" |
| Acupoints | English + pinyin: "the Sānlǐ acupoint" |
| Body mechanics | 側身一閃 → "sidestepped" |

#### Italics

- Use `*asterisks*` ONLY for untranslated foreign terms: *jiānghú*, *qì*, *diǎnxué*
- NEVER italicize character names or place names

#### Inline Markers

Every footnote MUST have a `[N]` marker in the translated text, placed:
- Immediately after the footnoted term
- Outside any quotes: `"the 'Sānlǐ' acupoint"[1]`
- Sequential from `[1]`

#### Footnote Style — Philological Depth

> WRONG: "A specific acupoint on the arm"
>
> RIGHT: "An acupoint on the lateral forearm, known in traditional medicine for treating pain and inflammation; in martial arts, striking this point can cause numbness and loss of grip"

#### Content Types

`narrative` | `dialogue` | `verse` | `document` | `descriptive` | `thought`

---

### Translation Wrapper (`wrappers/content_block_translation_wrapper.py`)

The `ContentBlockTranslationWrapper` wraps the LLM call with:

| Feature | Detail |
|---------|--------|
| Suppress list | 114 wuxia terms injected into system prompt |
| Cross-block dedup | `FootnoteContextAccumulator` tracks all footnoted ideograms |
| Already-footnoted context | Up to 30 previously footnoted terms injected into prompt |
| Glossary context | Scans source text for glossary terms (up to 30 matches) |
| Empty footnote filter | Rejects ghost footnotes (model emitted key but no content) |
| Pinyin validation | Corrects model pinyin against `pypinyin` ground truth |
| Marker placement | 10-strategy search to ensure `[N]` sits next to its term |

#### Pinyin Validation

After filtering, each footnote's pinyin is validated character-by-character against `pypinyin`:

```
道長: model=dàolǎng → corrected=dào zhǎng
```

Preserves the model's capitalization style.

#### Marker Placement Strategies (in order)

| # | Strategy | Example |
|---|----------|---------|
| 1 | Exact pinyin with tones | `Wǔdāng Shān` |
| 2 | Pinyin without tones | `Wudang Shan` |
| 3 | First word with tones | `Wǔdāng` |
| 4 | First word without tones | `Wudang` |
| 5 | Joined form | `Jǐnyīwèi` |
| 6 | Quoted terms from explanation | `'Embroidered Uniform Guard'` |
| 7 | "translated as X" pattern | `Governor-General` |
| 8 | Hyphenated caps in explanation | `Governor-General` |
| 9 | Multi-word caps in explanation | `Iron Sand Palm` |
| 10 | Positional mapping from source | Find 鐵砂掌 in Chinese → proportional position in English → nearest sentence boundary |

---

## Stage 4: 4-Phase Footnote Cleanup

**File:** `utils/remove_trivial_footnotes.py`
**Model:** `gpt-4.1-nano` (cheap, fast)
**Typical result:** 93–98% of raw footnotes removed; only genuine cultural/historical content survives.

### Phase 1 — Suppress List (programmatic, instant)

Matches footnote ideograms against `config/suppress_list.json` (114 terms).

Categories: martial arts (江湖, 氣, 內功, 武林, 輕功…), weapons (劍, 刀), honorifics (前輩, 晚輩), common nouns (馬, 銀兩), meta-narrative (下回分解), emotions/actions (搖頭, 嘆息).

**Typical removal: 10–40 per chapter.**

### Phase 1.5 — Heuristic Patterns (programmatic, instant)

| Pattern | Detects | Example |
|---------|---------|---------|
| `CHAR_NAME` | "A personal name", "A character's name" | Removes all |
| `FREQ_NAME` | 2–3 char ideograms appearing 3+ times in book source (likely fictional names) | Removed unless explanation has cultural signals |
| `TRIVIAL_ACTION` | Emotions, gestures, actions | "sighing", "shaking head" |
| `SHORT_NO_CULTURE` | Explanations < 80 chars with no cultural signals | Cultural signals: dynasty, emperor, Buddhist, Taoist, martial technique, etc. |

**Typical removal: 130–250 per chapter.**

### Phase 2 — AI Scoring, In-Context (GPT-4.1-nano)

Sends footnote + 300 chars of surrounding paragraph to the model.

Scores on two axes:
- **Triviality** (0–100): higher = more trivial
- **Cultural specificity** (0–100): higher = more culturally rich

**Removal logic:**
- `triviality ≥ 80` → remove (unless `cultural ≥ 80` AND model says keep)
- `model.should_remove = True` AND `triviality ≥ 50` → remove

Also performs work-wide deduplication (first occurrence only).

**Batch size:** 10 footnotes per API call | **Temperature:** 0.3
**Typical removal: 30–50 per chapter.**

### Phase 3 — Context-Free Ideogram Review (GPT-4.1-nano)

Collects unique ideogram→explanation pairs across the entire work. Sends ONLY ideogram + explanation — no paragraph context.

Stricter prompt: "Does this add genuine cultural knowledge?"

This is the "killer" phase — catches junk that Phase 2 preserves because the model is more lenient when it sees surrounding narrative.

Removes ALL occurrences of flagged ideograms across all blocks.

**Temperature:** 0.1 (very consistent)
**Typical removal: 60–95 per chapter.**

### Protected Ideograms

Footnotes whose pinyin appears as italicized text in the translation (e.g., *shīxiōng*, *qì*) are protected from removal on first occurrence — the reader needs the explanation.

---

## Stage 5: Marker Repositioning + AI Verification

### Heuristic Repositioning (`_reposition_markers`)

After cleanup removes footnotes, surviving markers may be orphaned or misplaced. This step:

1. Strips all `[N]` markers from the text
2. For each surviving footnote, finds the term using the same 10-strategy search (pinyin → explanation → positional mapping)
3. Places marker at the term, outside quotes/parens
4. Removes footnotes whose term cannot be found (unanchored)
5. Sorts by text position → assigns sequential keys

### AI Verification (`_ai_verify_marker_positions`)

A cheap nano pass on each block with surviving footnotes (~10–15 blocks per chapter, ~20–30 footnotes total).

**Prompt:** "Verify each [N] marker is placed IMMEDIATELY after the term it annotates. If misplaced, move it."

**Rules:**
- Do NOT change the translation text
- Do NOT add or remove footnotes
- Do NOT change numbering
- ONLY move misplaced markers

**Sanity check:** Rejects if the model changes marker count (hallucinated add/remove).

---

## Stage 6: Renumbering + Orphan Sanitization

### Chapter-Continuous Renumbering (`_renumber_chapter_continuous`)

Footnotes renumbered continuously across each chapter: block 1 has `[1][2]`, block 2 continues at `[3]`, etc.

Runs **twice**: once after heuristic repositioning, once after AI verification.

### Orphan Marker Sanitization (`_sanitize_orphan_markers`)

Strips any `[N]` marker from the text that has no matching footnote in the block's footnote array. Also runs twice.

---

## Stage 7: Validation

### Structural Integrity (`validate_footnote_integrity`)

Checks:
- No orphaned markers (markers without matching footnotes)
- Footnote keys are chapter-continuous (monotonically increasing across blocks)
- No duplicate ideograms within the same block

### Quality Validation (AI, optional)

Uses the validation prompt to score:
- Translation quality (accuracy, literary register, tone)
- Footnote quality (pinyin accuracy, cultural accuracy, depth)
- Footnote appropriateness (no spoilers, no fictional names, no obvious)
- Footnote density (narrative: 2–5 max 8; dialogue: 0–2)
- Marker integrity (every key has matching marker)

---

## Stage 8: EPUB Generation

**File:** `processors/epub_builder.py`
**CSS:** `styles/kindle.css`

### Structure

```
EPUB/
├── mimetype
├── META-INF/container.xml
├── EPUB/
│   ├── content.opf          (metadata, manifest, spine)
│   ├── styles/kindle.css
│   ├── title.xhtml           (bilingual title page)
│   ├── chapter_001.xhtml     (chapter with inline footnotes)
│   ├── chapter_002.xhtml
│   ├── nav.xhtml             (EPUB3 navigation)
│   └── toc.ncx               (legacy NCX)
```

### Title Page

- English title (large, bold)
- Chinese subtitle (smaller, gray)
- Author (English + Chinese)
- Series info if available: "Series Name — Book NN of MM"

### Chapter Format

```html
<h2>
  Chapter 1: Iron Arrow Divine Bow...
  <span class="chapter-chinese">第一回　鐵矢神弓...</span>
</h2>

<p class="narrative">The caravan pressed westward...</p>
<p class="dialogue">"Brother Gěng, you hold great admiration..."</p>

<!-- Inline noteref -->
<a epub:type="noteref" href="#fn-ch1-3">[3]</a>

<!-- Chapter-end footnotes -->
<section class="chapter-footnotes">
  <h3>Notes</h3>
  <div epub:type="footnote" id="fn-ch1-3" class="footnote-entry">
    <p><strong>武當山</strong> (Wǔdāng Shān) — A sacred Taoist mountain...</p>
  </div>
</section>
```

### Dialogue Splitting

Each content block is split into dialogue and narrative segments:
- Lines starting with `"` or `\u201c` tagged as `<p class="dialogue">`
- Other lines tagged as `<p class="narrative">`
- Split quotes preserved: `"start," he said, "end."` stays together
- Inline quoted terms (< 30 chars) merged into surrounding narrative

### Transition Margins

When switching between narrative ↔ dialogue, adds `margin-top: 0.8em` for visual separation.

### Footnote Popups (EPUB3/Kindle)

Uses EPUB3 `epub:type="noteref"` + `epub:type="footnote"` for Kindle tap-to-view popups. Fallback: visible `<section class="chapter-footnotes">` at chapter end.

### CSS Highlights

| Selector | Key styles |
|----------|-----------|
| `p.dialogue` | `text-indent: 1.5em; margin: 0.8em 0` |
| `p.narrative` | `text-indent: 1.5em; margin: 0.3em 0` |
| `p.thought` | `text-indent: 1.5em; margin: 0.3em 0` (not italic) |
| `div.verse` | `margin: 1em 2em; font-style: italic` |
| `blockquote.document` | `border-left: 3px solid #999` |
| `a.noteref` | `font-size: 0.85em; vertical-align: super; color: #0066cc` |
| `.chapter-footnotes` | `border-top: 1px solid #999; font-size: 0.9em` |
| `h2 .chapter-chinese` | `display: block; font-size: 0.7em; color: #666` |
| Kindle `@media amzn-kf8` | Hides `aside[epub:type="footnote"]` (uses popup instead) |

---

## Configuration

### Suppress List (`config/suppress_list.json`)

114 terms across categories:

- **Martial arts:** 江湖, 氣, 內功, 外功, 武林, 武功, 輕功, 點穴, 丹田, 內力, 真氣, 經脈, 穴道, 暗器, 掌門, 門派, 幫主, 拳, 劍, 刀, 抱拳, 武藝, 招式, 套路, 比武…
- **Honorifics:** 前輩, 晚輩, 弟子, 俠, 大俠, 少俠, 師傅, 師父…
- **Objects/places:** 銀兩, 客棧, 鑣局, 衙門, 官府, 綠林…
- **Common nouns:** 馬, 山, 公子, 小姐, 姐姐, 皇帝, 皇上…
- **Emotions/actions:** 搖頭, 嘆息, 嘆道, 咳嗽, 噗哧…
- **Meta-narrative:** 下回分解, 欲知後事如何

### Model Defaults

| Component | Model | Temperature |
|-----------|-------|-------------|
| Translation (body) | `gpt-4.1-mini` | 0.3 |
| Translation (metadata/titles) | `gpt-4.1-mini` | 0.3 |
| Phase 2 scoring | `gpt-4.1-nano` | 0.3 |
| Phase 3 review | `gpt-4.1-nano` | 0.1 |
| Marker verification | `gpt-4.1-nano` | 0.0 |

### Dependencies

```
openai>=1.0.0       # LLM API
pypinyin>=0.50.0     # Pinyin validation
ebooklib>=0.18       # EPUB generation
tqdm>=4.65.0         # Progress bars
python-dotenv>=1.0.0 # Environment config
```

---

## Data Schema

### Translated JSON

```json
{
  "meta": {
    "work_number": "D438",
    "title": "白髮魔女傳",
    "author": "梁羽生",
    "translation": {
      "title": "The Legend of the White-Haired Witch",
      "author": "Liáng Yǔshēng"
    }
  },
  "structure": {
    "table_of_contents": [
      {
        "title": "Chapter 1: Iron Arrow Divine Bow...",
        "title_zh": "第一回　鐵矢神弓...",
        "chapter_number": 1
      }
    ],
    "body": {
      "chapters": [
        {
          "title": "第一回　鐵矢神弓...",
          "translated_title": "Chapter 1: Iron Arrow Divine Bow...",
          "content_blocks": [
            {
              "id": "block_0001",
              "content": "Chinese source text...",
              "translated_content": "English text with Wǔdāng Shān[1] markers...",
              "content_type": "narrative",
              "footnotes": [
                {
                  "key": 1,
                  "ideogram": "武當山",
                  "pinyin": "Wǔdāng Shān",
                  "explanation": "A sacred Taoist mountain range..."
                }
              ]
            }
          ]
        }
      ]
    }
  }
}
```

### EPUB Builder Field Expectations

| Field | Used by EPUB builder |
|-------|---------------------|
| `meta.translation.title` | EPUB title + title page |
| `meta.translation.author` | EPUB author + title page |
| `chapter.translated_title` | Chapter heading + TOC entry |
| `block.translated_content` | Chapter body text |
| `block.content_type` | CSS class selection |
| `block.footnotes[].key` | Marker matching + popup linking |
| `block.footnotes[].ideogram` | Footnote display (bold) |
| `block.footnotes[].pinyin` | Footnote display (italic) |
| `block.footnotes[].explanation` | Footnote body text |

---

## Example Results

**D438 White-Haired Demoness, Chapter 1** (78 blocks):

| Metric | Value |
|--------|-------|
| Blocks translated | 78 |
| Raw footnotes generated | 31 |
| Empty footnotes filtered | 10 |
| Final footnotes | 21 |
| CJK in translated text | 0 (zero-ideogram rule PASS) |
| Pinyin corrections | 1 (道長: dàolǎng → dào zhǎng) |
| Markers placed inline | 18 (pinyin/explanation match) |
| Markers placed positionally | 3 (source text mapping) |
| Markers at end (fallback) | 0 |
| Dialogue paragraphs | 33 |
| EPUB size | 37.8 KB |

**D440 Seven Swords, Chapter 3** (359 raw footnotes → 4-phase cleanup):

| Phase | Removed | Running total |
|-------|---------|--------------|
| Phase 1 (suppress list) | 38 | 321 remaining |
| Phase 1.5 (heuristics) | 201 | 120 remaining |
| Phase 2 (AI in-context) | 33 | 87 remaining |
| Phase 3 (AI context-free) | 68 | 19 remaining |
| **Final preserved** | **26** | **93% removed** |

All 26 survivors: genuine cultural/historical content (Kangxi Emperor, Wudang, Dalai Lama, Zhuangzi, etc.)
