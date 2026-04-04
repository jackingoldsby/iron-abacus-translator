# Iron Abacus Translation Pipeline — Architecture

## Pipeline Overview

The Iron Abacus translation pipeline transforms cleaned Chinese JSON into translated, annotated English EPUBs. It operates as a DAG (directed acyclic graph) of 20 stages, each a `StageProcessor` subclass registered in `scripts/pipeline_runner.py`.

```
source_loader
    |
    v
metadata / toc / headings  (parallel)
    |
    v
body                        Translation (DeepSeek, 50 parallel workers)
    |
    v
qg_footnote_integrity       Quality gate: marker/footnote consistency
    |
    v
special                      Front/back matter translation
    |
    v
cleanup_6a                   Phase 1: Suppress list (programmatic)
    |
    v
cleanup_6b                   Phase 1.5 + 2: Heuristics + AI scoring (nano)
    |
    v
cleanup_6c                   Phase 3: Context-free ideogram review (nano)
    |
    v
cleanup_6d_dramatis          Dramatis Personae harvest + strip
    |
    v
qg_post_cleanup              Quality gate: post-cleanup integrity
    |
    v
wiki_enrich                  Wikipedia summary enrichment
    |
    v
validation                   Coverage + integrity check
    |
    v
review                       Consistency review (DeepSeek, chapter-level)
    |
    v
review_adjudicate            Accept/reject each finding (DeepSeek, per-finding)
    |
    v
correction_classify          Triage classifier (DeepSeek, per-block)
    |
    v
correction_apply             Focused corrections + post-processing
    |
    v
epub_build                   Crimson Folio EPUB3 generation
    |
    v
send_kindle                  Email to Kindle device
```

## Key Components

### 1. Translation (`body` stage)

**File**: `wrappers/content_block_translation_wrapper.py`

Translates each content block independently via DeepSeek. The system prompt is composed of:

- **Genre/author brief** — from `PROMPT_REGISTRY` in `translation_prompts.py`, keyed by author (金庸, 梁羽生, etc.) or genre (wuxia, gong'an, shenmo)
- **Mechanical rules** — `_MECHANICAL_RULES_PREAMBLE` + `_SHARED_TRANSLATION_RULES`, unified for all providers
- **Suppress list** — 120+ terms the model must not footnote

The lean prompt (~22K chars) covers:
- Core translation quality (rules 1-5: zero ideograms, pinyin, tense, gender, honorifics)
- Footnote style (rules 6-7: marker placement, philological depth)
- Generation-time quality (rules 8-9: epithet wordplay, loanwords, paratactic chains, verse, combat logic, no phantom/meta/redundant footnotes)

Heavy enforcement rules (weapons, register, idioms, measurements, settlement hierarchy) are delegated to the correction pipeline.

**Parallelism**: All blocks across all chapters submitted to one `ThreadPoolExecutor(max_workers=50)`. Results keyed by `(chapter_idx, block_id)`.

**Footnote dedup**: `FootnoteContextAccumulator` tracks already-footnoted ideograms across blocks. Race conditions possible with 50 parallel workers — the correction pipeline's dedup pass is the safety net.

### 2. Footnote Cleanup (stages 6a-6d)

**File**: `utils/remove_trivial_footnotes.py`

Four-phase cleanup reducing raw footnotes by 93-98%:

| Phase | Method | What it removes |
|-------|--------|-----------------|
| 1 (6a) | Suppress list match | 120+ common terms (江湖, 氣, 武林, etc.) |
| 1.5+2 (6b) | Heuristics + nano AI scoring | Character names, trivial actions, short explanations |
| 3 (6c) | Context-free ideogram review (nano) | Junk that Phase 2 preserves due to context leniency |
| DP (6d) | Dramatis Personae harvest | Character footnotes → DP section, stripped from body |

### 3. Consistency Review (`review` stage)

**File**: `processors/consistency_reviewer.py` — `ConsistencyReviewer`

Chapter-level review using DeepSeek with sliding windows (25 blocks per window, 2-block overlap). Reviews 10 categories:

| Category | What it catches |
|----------|----------------|
| tense | Past/present drift, retrospective narration errors |
| gender | He/she confusion, gendered collective nouns (二人 as "two men") |
| style | Register breaks, anachronisms, dangling modifiers |
| register | Modern English in jianghu context (heist, mark, Messrs.) |
| honorific | English where pinyin expected, translated surnames |
| footnote | Missing culturally significant footnotes |
| pinyin | Missing tone marks, inconsistent romanization |
| date | Wrong reign year → CE conversion |
| weapon | 長劍 as "long sword", weapon idioms translated literally |
| idiom | Literal calques of curses/idioms |

**Stop-flagging list**: 9 categories the reviewer must NOT flag (wuxia epithets, calques, archaic diction, past perfect in dialogue, fictional factions, etc.)

### 4. Review Adjudicator (`review_adjudicate` stage)

**File**: `processors/consistency_reviewer.py` — `ReviewAdjudicator`

Second LLM pass that evaluates each review finding independently:
- Receives: finding + original block + proposed replacement + source Chinese + ±2 context blocks + referenced blocks from reviewer's note
- Returns: accept/reject with reason
- 50 parallel workers, one finding per request
- Only accepted findings applied via `ConsistencyReviewer.apply_findings(respect_accepted=True)`
- Block lookups keyed by `(chapter_idx, block_id)` to prevent cross-chapter bleed

### 5. Correction Classifier (`correction_classify` stage)

**File**: `processors/correction_classifier.py` — `CorrectionClassifier`

DeepSeek-based tagger that classifies each translated block into issue categories. 50 parallel workers, one block per request.

**11 categories**:

| Category | What it detects |
|----------|----------------|
| measurement | Western units, un-italicized pinyin measurements/onomatopoeia |
| weapon | "long sword", weapon type overrides, domestic 棒 as cudgel |
| register | Modern slang, corporate English, Cold War terminology |
| footnote_placement | Markers on wrong words, inline glosses, mismatched ideograms |
| footnote_consolidation | Adjacent redundant footnotes |
| footnote_missing | Missing acupoint/sect/allusion/reign-date footnotes, fictional footnotes to remove |
| honorific | English honorifics, bare pinyin without asterisks |
| idiom_curse | Literal calques of curses/idioms |
| supernatural | European creatures substituted for Chinese |
| technique_name | Comical verbs, combat direction errors, trivial technique footnotes |
| organ_metaphor | Literal body-organ calques |

Blocks tagged `clean` skip the correction stage entirely. Typical: 40-50% tagged, 50-60% clean.

### 6. Correction Applicator (`correction_apply` stage)

**File**: `processors/correction_applicator.py` — `CorrectionApplicator`

For each tagged block, builds a focused correction prompt from only the relevant specialist rules (from `correction_prompts.py`). Each prompt is ~1-3K tokens vs the old 29K monolithic prompt.

**Specialist prompts** (`processors/correction_prompts.py`):

Each category maps to a `CORRECTION_PROMPTS[category]` string. The system template wraps them with forceful instructions ("you MUST fix EVERY instance").

After LLM corrections, runs a 6-step programmatic post-processing chain:

```
1. Footnote relocation     (programmatic find + LLM marker placement)
2. Suppress list + dedup   (programmatic: ideogram, pinyin, containment matching)
3. Bad footnote sweep      (LLM per-footnote: KEEP / TRIM / REMOVE, 50 workers)
4. Marker placement verify (LLM per-block: move misplaced markers, 50 workers)
5. In-block marker dedup   (programmatic: keep last occurrence of duplicates)
6. Finalize                (programmatic: punctuation fix + chapter-continuous renumbering)
```

#### Step 1: Footnote Relocation
For each footnote, checks if its ideogram appears in the block's source Chinese. If not, searches all blocks in the chapter for the first occurrence. Moves the footnote to the correct block and uses LLM to place the marker at the right position in the English text.

#### Step 2: Dedup
- Checks suppress list first (strips any suppressed terms the corrector re-added)
- Exact ideogram match
- Containment match (越王 contains 越, which was already seen via 吳越)
- Pinyin match (catches variant characters)
- Keeps first occurrence only

#### Step 3: Bad Footnote Sweep
Each surviving footnote evaluated independently by LLM:
- **KEEP**: genuine historical/cultural content
- **TRIM**: strip meta-commentary, filler, translation convention explanations — keep the valid core
- **REMOVE**: entirely fictional, trivially obvious, fully redundant with surrounding text

#### Step 4: Marker Placement Verification
Each block with footnotes sent to LLM with the footnote list. LLM verifies each `[N]` marker is on the English word matching footnote N's ideogram. Moves misplaced markers. Guards against duplicate markers (rejects LLM output if dupes introduced).

#### Step 5: In-Block Marker Dedup
Programmatic: if a consolidated footnote produced two `[28]` markers in the same block, keeps the last occurrence (after the final term in a group).

#### Step 6: Finalize
Single programmatic pass:
- Move markers before punctuation: `term.[1]` → `term[1].`
- Renumber footnotes continuously per chapter: `[1], [2], [3]...`
- Strip orphaned markers (no matching footnote)
- Clean up double spaces

### 7. EPUB Build (`epub_build` stage)

**File**: `crimson_folio/builders/epub_builder.py`

Generates EPUB3 with:
- Title page (bilingual, series info, volume number)
- Chapters with popup footnotes
- CSS theme (Kindle-optimized)

Filename format: `Author - Title Vol. N (Series #NN).epub`
- Volume number from JSON metadata `volume` field
- Series info from DuckDB catalog
- No leading zeros on title page display; zero-padded in filename for sort order

### 8. Kindle Delivery (`send_kindle` stage)

**File**: `crimson_folio/delivery/kindle_sender.py`

SMTP-based email delivery to Kindle devices.

## File Map

```
iron_abacus_translator/
├── processors/
│   ├── translation_prompts.py      # Prompt registry, mechanical rules, validation prompt
│   ├── consistency_reviewer.py     # ConsistencyReviewer + ReviewAdjudicator
│   ├── correction_classifier.py    # CorrectionClassifier (triage tagger)
│   ├── correction_applicator.py    # CorrectionApplicator + 6-step post-processing
│   └── correction_prompts.py       # CORRECTION_PROMPTS dict, specialist rules
│
├── wrappers/
│   └── content_block_translation_wrapper.py  # Per-block translation wrapper
│
├── utils/
│   ├── remove_trivial_footnotes.py  # 4-phase footnote cleanup
│   ├── build_dramatis_personae.py   # DP harvest
│   ├── historical_ref_cache.py      # Wikipedia enrichment cache
│   └── clients/                     # LLM client wrappers
│
├── workflows/
│   └── translation_pipeline_dag.py  # DAG definition (20 nodes)
│
├── scripts/
│   └── pipeline_runner.py           # Stage processors + pipeline runner
│
├── config/
│   └── suppress_list.json           # 120+ suppressed footnote terms
│
├── docs/
│   ├── review_d60_ch3_4_prompt_guidance.md  # 49 review principles (staging area)
│   └── pipeline_architecture.md     # This file
│
└── cli/
    └── run_pipeline.py              # CLI entry point

crimson_folio/
├── builders/
│   └── epub_builder.py              # EPUB3 generation
├── styles/
│   └── kindle.css                   # Kindle-optimized CSS
└── delivery/
    └── kindle_sender.py             # Kindle email delivery
```

## Performance (D61a — 1,641 blocks, 10 chapters)

| Stage | Duration |
|-------|----------|
| Body translation (50 workers) | 7.3 min |
| Footnote cleanup (4-phase) | ~8 min |
| Review + adjudication | 3.2 min |
| Correction classify | 48s |
| Correction apply + post-processing | 5 min |
| EPUB + Kindle | 5s |
| **Total** | **29.6 min** |

## Cost Estimate (DeepSeek)

| Book size | Blocks | Est. cost |
|-----------|--------|-----------|
| Short (130K chars) | ~1,200 | ~$1-2 |
| Medium (400K chars) | ~3,000 | ~$3-5 |
| Long (480K chars) | ~5,500 | ~$5-9 |

With DeepSeek prefix caching, costs are at the lower end. Full catalog (~150 books) estimated at $300-500.
