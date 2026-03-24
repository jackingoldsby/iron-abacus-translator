# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**📖 For organizational standards and coding conventions, see [docs/BEST_PRACTICES.md](docs/BEST_PRACTICES.md)**

## Project Overview

**Iron Abacus Translator** - Classical Chinese literature translation pipeline: raw JSON through cleaning, AI structuring, translation with cultural footnotes, to final EPUB generation.

**Vision**: `Raw JSON → Clean → Structure → Translate → Footnotes → EPUB`

**Current Status**:
- ✅ JSON Cleaner (implemented)
- ✅ Post-Processing Tools (chapter alignment, TOC restructuring, embedded chapter detection)
- ✅ Validation Tools (sanity checker, sequence validator, TOC alignment validator)
- ✅ Content Structurer (implemented)
- ✅ Batch Pipeline (8-stage processing with metadata enrichment)
- ✅ Translation Orchestration (7-stage pipeline with AI footnotes + cleanup)
- ✅ Footnote Cleanup (4-phase: suppress list → heuristics → AI scoring → context-free review)
- 🚧 EPUB Builder (placeholder)

## Development Commands

### Environment Setup
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt  # For development
```

### Running Processors

```bash
# JSON cleaning (no API needed)
python cli/clean.py --input book.json --output cleaned.json --language zh-Hant

# AI-powered structuring (requires OPENAI_API_KEY)
python cli/structure.py --input cleaned.json --output structured.json --max-workers 3

# Structure validation (requires OPENAI_API_KEY for AI classification)
python cli/validate_structure.py --input cleaned.json --output validation_report.json

# Translation orchestration (7-stage pipeline with footnote cleanup)
python scripts/orchestrate_translation_pipeline.py D1379  # Translate work D1379
python scripts/orchestrate_translation_pipeline.py D1379 --volume a  # Specific volume
python scripts/orchestrate_translation_pipeline.py D1379 --resume  # Resume from checkpoint

# Standalone footnote cleanup (if needed separately)
python cli/cleanup_character_footnotes.py --input translated.json --output-dir ./cleaned

# Future processors (placeholders)
python cli/build_epub.py --input translated.json --output book.epub
```

### Testing
```bash
pytest                          # Run all tests
pytest tests/test_specific.py   # Run specific test
pytest -v                       # Verbose output
pytest --cov                    # Coverage report
```

### Code Quality
```bash
black processors ai utils cli   # Format code
flake8 processors ai utils cli  # Lint code
mypy processors ai utils cli    # Type checking
```

### Package Scripts (npm)
```bash
npm run clean      # Run JSON cleaner
npm run structure  # Run content structurer
npm run test       # Run pytest
npm run lint       # Run flake8
npm run format     # Run black
```

## Agent Delegation

For detailed implementation guidance, consult specialized agents in `.claude/agents/`:

### Translation & Processing
- **JSON Cleaning & Structuring**: `json-book-restructurer.md` - Build scripts for raw JSON → cleaned format
- **Translation Service**: `wuxia-translator-annotator.md` - Build translation service with cultural annotations
- **Translation Pipeline**: `translation-annotation-orchestrator.md` - Orchestrate 7-stage translation workflow

### Footnote Processing
- **4-Phase Trivial Removal**: `utils/remove_trivial_footnotes.py` - Main pipeline (suppress → heuristics → AI scoring → context-free review)
- **Character Footnote Cleanup**: `footnote-name-cleanup.md` - Legacy character footnote removal (superseded by Phase 1.5)
- **Duplicate Footnote Removal**: `footnote-deduplicator.md` - Legacy dedup scripts (superseded by Phase 2+3)
- **Triviality Removal**: `footnote-triviality-remover.md` - Agent for building removal scripts

### Workflow & Output
- **Batch Processing**: `workflow-orchestrator.md` - Design batch workflows with parallel execution
- **Stage Creation**: `stage-creation-manager.md` - Create and validate workflow stages with enforced attributes
- **EPUB Formatting**: `epub-format-designer.md` - Design formatting rules for EPUB output
- **UI Management**: `translation-ui-manager.md` - Build web UI for translation job management

### When to Use Agents
- **Implementation tasks**: Use agents to generate/modify code
- **Architecture questions**: Use agents for design guidance
- **Debugging**: Agents can analyze logs and suggest fixes
- **Documentation**: CLAUDE.md provides quick reference; agents provide deep dives

## Architecture

### Pipeline Structure

```
processors/
├── json_cleaner.py          [IMPLEMENTED] Raw JSON → Discrete blocks
├── content_structurer.py    [IMPLEMENTED] Blocks → Semantic types
├── structure_validator.py   [IMPLEMENTED] AI-powered TOC/structure validation
├── translator.py            [IMPLEMENTED] Classical Chinese translation with cultural footnotes
├── footnote_generator.py    [INTEGRATED] Part of translator.py
└── epub_builder.py          [PLACEHOLDER] Generate EPUB file

utils/
├── topology_analyzer.py         [IMPLEMENTED] Structure analysis without modification
├── sanity_checker.py            [IMPLEMENTED] Early validation with metadata enrichment
├── catalog_metadata.py          [IMPLEMENTED] Extract metadata from SQLite catalog
├── chapter_sequence_validator.py [IMPLEMENTED] Chinese chapter numbering validation
├── toc_alignment_validator.py   [IMPLEMENTED] OpenAI-powered TOC validation
├── fix_chapter_alignment.py     [IMPLEMENTED] Fix EPUB metadata mismatches
├── restructure_toc.py           [IMPLEMENTED] Convert TOC to structured navigation
├── embedded_chapter_detector.py [IMPLEMENTED] Detect/extract chapters from intro sections
├── clients/                     [IMPLEMENTED] API wrappers (OpenAI, Anthropic)
└── http_legacy/                 [LEGACY] HTTP with retry logic (deprecated)

scripts/
├── batch_process_books.py   [IMPLEMENTED] 8-stage pipeline with metadata enrichment
└── fix_embedded_chapter1.py [IMPLEMENTED] Standalone embedded chapter extractor

ai/
└── assistant_manager.py     [IMPLEMENTED] Manage OpenAI assistants

cli/
├── clean.py                 [IMPLEMENTED] CLI for json_cleaner
├── structure.py             [IMPLEMENTED] CLI for content_structurer
├── validate_structure.py    [IMPLEMENTED] CLI for structure_validator
├── translate.py             [IMPLEMENTED] CLI for translator (use orchestrate_translation_pipeline.py for production)
├── cleanup_character_footnotes.py [IMPLEMENTED] CLI for character footnote cleanup
└── build_epub.py            [PLACEHOLDER] CLI for epub_builder
```

### Data Flow

**Standard Batch Pipeline (8 Stages)**:
```
RAW INPUT (source JSON in individual directories)
   ↓
[Stage 1] utils/topology_analyzer.py
   → Analyze JSON structure without modifications
   → Estimate tokens for AI processing
   → Identify content locations and nesting depth
   → Deterministic, no API calls
   ↓
[Stage 2] utils/sanity_checker.py
   → Extract metadata from catalog SQLite database
     (work_number, title, author, volume)
   → Validate Chinese chapter numbering sequences
   → Detect missing, duplicate, or out-of-order chapters
   → Parse Chinese numerals: 一二三...十廿卅卌...百千
   → Non-fatal validation (continues on errors)
   ↓
[Stage 3] processors/json_cleaner.py
   → Recursive extraction from nested structures
   → TOC auto-detection
   → Block ID generation (block_0000, block_0001...)
   → EPUB ID generation (heading_0, para_1...)
   → Enrich with catalog metadata (work_number, title, author, volume)
   ↓
CLEANED JSON (discrete blocks + metadata)
   ↓
[Stage 4] utils/embedded_chapter_detector.py
   → Detect chapters embedded in introduction/title pages
   → Extract ANY chapter marker (一、二、三... 廿、卅、卌... 第N章/回)
   → Works for any starting chapter number (not limited to Chapter 1)
   → Handles multi-volume works with different numbering schemes
   → Creates new chapter, renumbers existing, updates TOC
   → Removes chapter content from introduction section
   → Non-fatal (continues on errors)
   ↓
[Stage 5] utils/fix_chapter_alignment.py
   → Fix EPUB metadata mismatches
   → Match chapter titles to actual content headings
   → Support 第N回 (hui) and 第N章 (zhang) formats
   → Support special numerals: 廿 (20), 卅 (30), 卌 (40)
   → Split combined chapters
   → Deterministic, pattern-based
   ↓
[Stage 6] utils/restructure_toc.py
   → Convert TOC from text blob to structured list
   → Create chapter references for EPUB navigation
   → Handle blob format (space-separated entries)
   → Generate TOC from chapters when missing
   → Support Chinese numerals including 廿/卅/卌
   → Fuzzy matching for variants
   ↓
[Stage 7] Comprehensive Validation (3 validators)
   → batch_process_books.py orchestrates multiple validators:

   A. processors/structure_validator.py
      - AI-powered chapter classification (front_matter, body, back_matter)
      - Detects special sections (preface, afterword, appendix)
      - Quality scoring

   B. utils/toc_chapter_validator.py
      - Extracts actual headings from content_blocks
      - OpenAI-powered semantic TOC/chapter title matching
      - Detects missing chapters, title mismatches
      - Handles Chinese numeral variations (廿/卅/卌)

   C. utils/toc_body_count_validator.py [NEW]
      - Validates TOC entry count matches body chapter count
      - Identifies specific chapters missing from TOC
      - Detects extra TOC entries not in body
      - Fast, deterministic (no API calls)

   → All validators run in parallel
   → Results merged with error/warning categorization
   → Requires OPENAI_API_KEY for validators A & B
   ↓
VALIDATED JSON (ready for translation)
```

**Translation Orchestration Pipeline (7 Stages)**:

> **See also**: [Translation Orchestration Commands](#translation-orchestration-commands) for usage examples and output structure.

```
CLEANED & VALIDATED JSON
   ↓
scripts/orchestrate_translation_pipeline.py
   ↓
[Stage 1] METADATA Translation
   → Translate title, author, publisher
   → NO footnotes (clean metadata only)
   → Output: Translated meta block
   ↓
[Stage 2] TOC Translation
   → Translate table of contents entries
   → NO footnotes (clean navigation)
   → Preserve chapter references
   ↓
[Stage 3] HEADINGS Translation
   → Translate chapter titles/headings
   → NO footnotes (clean headings)
   → Sequential processing
   ↓
[Stage 4] BODY Translation
   → Translate main content blocks
   → WITH cultural/historical footnotes
   → AI-powered footnote generation:
     • Character names with pinyin (Yáng Lùchán[1])
     • Cultural concepts (氣[2] - vital energy)
     • Historical references
     • Martial arts terminology
   → Parallel processing (configurable workers)
   → Checkpoint/resume support
   ↓
[Stage 5] SPECIAL SECTIONS Translation
   → Translate front_matter/back_matter
   → WITH footnotes for cultural content
   → Prefaces, afterwords, appendices
   ↓
[Stage 6] FOOTNOTE PROCESSING — 4-PHASE TRIVIAL REMOVAL ✨
   → `utils/remove_trivial_footnotes.py` (TrivialFootnoteRemover)
   → Work-level processing (entire work at once)
   → Footnote renumbering + orphan marker sanitization after each phase
   → Config: `config/wuxia_suppress_list.json` (100+ suppressed terms)
   → Typical reduction: 93-98% of raw footnotes removed
   → Only genuinely valuable cultural/historical footnotes survive

   [Phase 1] SUPPRESS LIST (programmatic, no API, instant)
   → Matches footnote ideograms against `config/wuxia_suppress_list.json`
   → 100+ common wuxia terms: 江湖, 氣, 內功, 武林, 輕功, 劍, 刀, etc.
   → Also removes: meta-narrative (下回分解), common nouns (馬, 銀子, 山)
   → Removes footnotes with empty explanations
   → Typical: ~10-40 removed per chapter

   [Phase 1.5] HEURISTIC PATTERNS (programmatic, no API, instant)
   → Pattern-based detection of trivial footnote categories:
     • CHAR_NAME: "A personal name", "A character's name" patterns
     • FREQ_NAME: 2-3 char ideograms appearing 3+ times in book source
       (likely fictional character names), no historical signals
     • TRIVIAL_ACTION: emotions, gestures, actions ("sighing", "shaking head")
     • SHORT_NO_CULTURE: explanations < 80 chars with no cultural signals
       (dynasty, emperor, Buddhist, Taoist, martial technique, etc.)
   → Cultural signal regex prevents false positives on genuinely
     cultural footnotes (Tibetan, Han Chinese, dynasty names, etc.)
   → Word-boundary fix on BCE/CE/AD/BC prevents matching inside words
   → Typical: ~130-250 removed per chapter

   [Phase 2] AI SCORING — IN-CONTEXT (OpenAI GPT-4.1-nano)
   → Scores remaining footnotes with paragraph context
   → Two axes: triviality (0-100) + cultural_specificity (0-100)
   → Removal: triviality ≥ 80 removes unless cult ≥ 80 AND model says keep
   → Also: model should_remove=True AND triviality ≥ 50 → remove
   → Includes work-wide deduplication by ideogram (first occurrence only)
   → Batch size: 25 footnotes per API call
   → Typical: ~30-50 removed per chapter

   [Phase 3] AI REVIEW — CONTEXT-FREE BY IDEOGRAM (GPT-4.1-nano)
   → Collects unique ideogram→explanation pairs across entire work
   → Sends ONLY ideogram + explanation (no paragraph context)
   → Stricter prompt: "Does this add genuine cultural knowledge?"
   → Context-free review catches junk that Phase 2 preserves
     (model is more lenient when it sees surrounding narrative)
   → Removes all occurrences of flagged ideograms across all blocks
   → Temperature: 0.1 (very consistent)
   → Typical: ~60-95 removed per chapter (the "killer" phase)

   [Legacy 6a] CHARACTER FOOTNOTE CLEANUP [STILL AVAILABLE]
   → Separate script: `utils/cleanup_character_footnotes_standalone.py`
   → AI classification of fictional vs historical characters
   → Can run independently: --skip-character-footnote-cleanup
   → Largely superseded by Phase 1.5 FREQ_NAME + Phase 3 review

   [Legacy 6b] DUPLICATE TERM CLEANUP [SCRIPT GENERATOR]
   → Use footnote-deduplicator agent to generate scripts
   → Largely superseded by Phase 2 dedup + Phase 3 review
   ↓
[Stage 7] VALIDATION
   → Verify translation completeness
   → Check footnote marker integrity
   → Quality scoring
   → Generate final report
   ↓
TRANSLATED JSON (ready for EPUB)
   → English translation with optimized footnotes
   → WIP files saved for each stage
   → Detailed logs and progress reports
   ↓
processors/epub_builder.py [TODO]
   → EPUB 3.0 generation
   → Internal linking via block IDs
   ↓
FINAL EPUB FILE
```

### Translation Orchestration Commands

> **See also**: [Translation Orchestration Pipeline (7 Stages)](#data-flow) for detailed workflow and stage descriptions.

**Basic Usage**:
```bash
# Translate single work
python scripts/orchestrate_translation_pipeline.py D1379

# Translate specific volume
python scripts/orchestrate_translation_pipeline.py I1046 --volume a

# Resume from checkpoint (if interrupted)
python scripts/orchestrate_translation_pipeline.py D1379 --resume

# Process specific stages only
python scripts/orchestrate_translation_pipeline.py D1379 --start-stage 4 --end-stage 6

# Dry run (no file writes)
python scripts/orchestrate_translation_pipeline.py D1379 --dry-run
```

**Output Structure**:
```
/Users/jacki/project_files/translation_project/
├── wip/                                    # Work-in-progress files
│   ├── stage_1_metadata/
│   ├── stage_2_toc/
│   ├── stage_3_headings/
│   ├── stage_4_body/
│   ├── stage_5_special/
│   ├── stage_6_cleanup/                   # After footnote cleanup
│   └── stage_7_validation/
├── translation_data/
│   ├── translated_D1379_偷拳_白羽.json   # Final output
│   └── logs/
│       ├── D1379_translation.log          # Main translation log
│       ├── D1379_stage_1_metadata.json    # Stage-specific logs
│       ├── D1379_stage_2_toc.json
│       ├── D1379_stage_3_headings.json
│       ├── D1379_stage_4_body.json
│       ├── D1379_stage_5_special.json
│       ├── D1379_stage_6_cleanup.json     # Footnote cleanup details
│       ├── D1379_stage_7_validation.json
│       └── checkpoints/
│           └── D1379_checkpoint.json      # Resume checkpoint
```

**Footnote Cleanup Results** (Stage 6 — 4-Phase Pipeline):
- Example metrics (D440 七劍下天山 ch3, 359 raw footnotes):
  - Phase 1 (suppress list): -38
  - Phase 1.5 (heuristics): -201
  - Phase 2 (API in-context): -33
  - Phase 3 (API context-free): -68
  - **Final preserved: 26 (93% removed)**
  - All 26 survivors: genuine cultural/historical content
    (Kangxi Emperor, Wudang, Dalai Lama, Zhuangzi, etc.)
- Key files:
  - `utils/remove_trivial_footnotes.py` — TrivialFootnoteRemover
  - `config/wuxia_suppress_list.json` — 100+ suppressed terms
  - `processors/translation_prompts_v2.py` — V2 translation prompts with suppress list injection

## Key Implementation Details

> **Note**: For detailed implementation, see specialized agents in `.claude/agents/` and source code documentation.

### JSON Cleaner (processors/json_cleaner.py)

**Purpose**: Transform raw JSON → discrete content blocks with EPUB IDs

**Key Features**:
- Recursive extraction from arbitrary nesting depths
- Auto-detects TOC (Chinese/English keywords)
- Generates block IDs (`block_0000`) and EPUB IDs (`heading_0`, `para_1`)
- Enriches with catalog metadata (work_number, title, author, volume)

**See**: `json-book-restructurer` agent for building cleaning scripts

**Quick Start**: `python cli/clean.py --input book.json --output cleaned.json`

### Catalog Metadata Extractor (utils/catalog_metadata.py)

**Purpose**: Extract work metadata from SQLite catalog (work_number, title, author, volume)

**Main Class**: `CatalogMetadataExtractor` - Query by directory name or work number

**Usage**: Automatically integrated into batch processing pipeline (Stage 2)

### Chinese Chapter Sequence Validator (utils/chapter_sequence_validator.py)

**Purpose**: Validate chapter numbering (gaps, duplicates, out-of-order)

**Supports**: Chinese numerals including special forms 廿 (20), 卅 (30), 卌 (40)

**Issue Types**: gap, duplicate, out_of_order, nonstandard_start

**Usage**: Integrated into sanity checker (Stage 2 of batch pipeline)

### Sanity Checker (utils/sanity_checker.py)

**Purpose**: Early validation + metadata enrichment (Stage 2)

**Combines**: Catalog metadata extraction + chapter sequence validation

**Behavior**: Non-fatal - continues processing even with errors

**Output**: Metadata, sequence issues, error summary

### Chapter Alignment Fixer (utils/fix_chapter_alignment.py)

**Purpose**: Match chapter titles to actual content headings (Stage 5)

**Features**: Splits combined chapters, handles 第N回/章 formats, supports special numerals (廿/卅/卌)

**Known Issue**: Assumes books start at Chapter 1 (some multi-volume works start at Ch 2+)

**Usage**: Automatically runs in batch pipeline Stage 5

### Embedded Chapter Detector (utils/embedded_chapter_detector.py)

**Purpose**: Extract chapters embedded in introduction/title pages (Stage 4)

**Common Pattern**: In Chinese novels, first chapter often embedded in intro/title page

**Features**:
- Detects ANY chapter marker (一、二、三... 廿、卅、卌... 第N章/回)
- Handles multi-volume works with different numbering schemes
- Extracts chapter, updates TOC, cleans introduction

**Usage**: Auto-runs in batch pipeline Stage 4, or `scripts/fix_embedded_chapter1.py` standalone

### TOC Restructurer (utils/restructure_toc.py)

**Purpose**: Convert TOC from text blob → structured navigation (Stage 6)

**Features**: Parses space-separated entries, creates chapter references, generates TOC when missing, fuzzy matching

**Support**: Chinese numerals including 廿/卅/卌

**Usage**: Auto-runs in batch pipeline Stage 6

### TOC/Chapter Validation Tools

**Three complementary validators** (all run in Stage 7):

1. **TOC/Body Count Validator** (`utils/toc_body_count_validator.py`)
   - Fast, deterministic count validation (no API calls)
   - Detects: missing chapters, extra TOC entries, count mismatches
   - CLI: `python utils/toc_body_count_validator.py input.json`

2. **TOC Alignment Validator** (`utils/toc_alignment_validator.py`) [LEGACY]
   - Simple AI-powered semantic validation
   - Model: GPT-4.1-nano, temperature: 0.1
   - Issue types: mismatch, number_mismatch, missing_chapter, typo
   - **Note**: Use Comprehensive validator for production

3. **Comprehensive TOC/Chapter Validator** (`utils/toc_chapter_validator.py`) [RECOMMENDED]
   - Extracts actual headings from `content_blocks` (advanced)
   - Detects: buried headings, topology mismatches, sequence gaps
   - AI validation for ambiguous cases (GPT-4.1-nano)
   - CLI: `python scripts/validate_toc_chapter_alignment.py`
   - Generates detailed JSON reports

**Usage**: All three run automatically in batch pipeline Stage 7

### Content Structurer (processors/content_structurer.py)

**Purpose**: Classify content blocks into semantic types (narrative, dialogue, verse, etc.)

**Features**:
- OpenAI Assistant-based classification
- Text chunking for large content (4000 chars max, 200 overlap)
- Batch processing with configurable workers (default: 3)
- Three modes: STRICT, FLEXIBLE (default), BEST_EFFORT

**Usage**: `python cli/structure.py --input cleaned.json --output structured.json --max-workers 3`

**See**: Source code for OpenAI Assistant pattern details

### Structure Validator (processors/structure_validator.py)

**Purpose**: AI-powered TOC/chapter alignment and section classification

**Validation Checks**:
1. TOC coverage - All chapters in TOC
2. TOC/chapter alignment - Titles match
3. Chapter numbering - No gaps/duplicates
4. Section classification - AI classifies as front_matter/body/back_matter
5. Special sections - Detects prefaces, afterwords, appendices, etc.

**Model**: GPT-4.1-nano, temperature: 0.3 (falls back to basic validation if API unavailable)

**Output**: `toc_coverage`, `structure_quality`, `is_valid`, `issues` list

**Usage**: `python cli/validate_structure.py --input cleaned.json --output report.json`

**Integration**: Auto-runs in batch pipeline Stage 7

### Assistant Manager (ai/assistant_manager.py)

**Purpose**: Manage OpenAI assistants with versioning

**Storage**: `.assistants/` directory (JSON configs)

**Key Methods**: create, get, list, update, delete, export, import, compare_versions

**CLI**: `python ai/assistant_manager.py [list|export|compare]`

**See**: `docs/AI_ASSISTANT_GUIDE.md` for detailed usage

## Configuration & Environment

### Required Environment Variables
```bash
export OPENAI_API_KEY=your-key-here        # For AI features
export ANTHROPIC_API_KEY=your-key-here     # Optional alternative
```

### Default Paths
- Input: `./input/book.json`
- Output: `./output/cleaned_book.json`
- Assistants: `.assistants/` (AI configs)
- Schemas: `schemas/` (JSON schemas)

### Processing Defaults

**json_cleaner.py**:
- DEFAULT_INPUT_PATH: `./input/book.json`
- DEFAULT_OUTPUT_PATH: `./output/cleaned_book.json`
- DEFAULT_LANGUAGE: `zh-Hant`

**content_structurer.py**:
- max_retries: 3
- retry_delay: 2.0s
- rate_limit_delay: 0.5s
- timeout: 300s (5 min)
- max_workers: 3
- max_chunk_size: 4000 chars
- chunk_overlap: 200 chars

**structure_validator.py**:
- model: "gpt-4.1-nano"
- temperature: 0.3 (low for consistent validation)
- timeout: 60s (1 min)
- save_report: True (generates validation JSON)

**toc_alignment_validator.py**:
- model: "gpt-4.1-nano"
- temperature: 0.1 (very low for consistency)
- batch_size: 20 (TOC/chapter pairs per API call)

**batch_process_books.py**:
- catalog_path: Required (path to SQLite catalog database)
- dry_run: False (set True to skip file writes)
- limit: None (process all files, or set number for testing)
- 8-stage pipeline: topology → sanity_check → cleaning → embedded_chapter → alignment → toc → validation (3 validators) → final

## Dependencies

From `requirements.txt`:
- `openai>=1.0.0` - OpenAI API client
- `anthropic>=0.18.0` - Anthropic API client
- `httpx>=0.24.0` - Async HTTP
- `beautifulsoup4>=4.12.0` + `lxml>=4.9.0` - HTML parsing
- `tenacity>=8.2.0` - Retry logic
- `tqdm>=4.65.0` - Progress bars
- `pytest>=7.4.0` - Testing

## Common Workflows

### Add New Block Type

1. Update `SchemaValidator.validate()` in content_structurer.py:
   ```python
   valid_types = [..., "new_type"]
   ```
2. Update assistant instructions to recognize new type
3. Update schema file if using validation

### Process Large Book

```bash
# Automatic chunking for >4000 chars
python cli/structure.py --input large_novel.txt --output result.json

# Disable chunking (may hit token limits)
python cli/structure.py --input novel.txt --no-chunking
```

### Debug AI Assistant

```bash
# List all assistants
python ai/assistant_manager.py list

# View specific config
python ai/assistant_manager.py export --name structuring --version latest

# Compare versions
python ai/assistant_manager.py compare --name structuring --version1 v1 --version2 v2
```

### Batch Processing (8-Stage Pipeline)

**Complete Pipeline** (recommended):
```bash
# Process all files with full pipeline
python scripts/batch_process_books.py \
  --source-dir /path/to/source_files \
  --output-dir /path/to/output \
  --catalog-path /path/to/wuxia_catalog.db \
  --log-dir ./logs

# Test on subset
python scripts/batch_process_books.py \
  --source-dir /path/to/source_files \
  --output-dir /path/to/output \
  --catalog-path /path/to/wuxia_catalog.db \
  --limit 10  # Process first 10 files only
```

**Individual Stage Processing**:
```bash
# Run specific post-processing stages
python utils/fix_chapter_alignment.py --input cleaned_book.json
python utils/restructure_toc.py --input cleaned_book.json
python -m utils.toc_alignment_validator cleaned_book.json

# Content structuring (separate from 6-stage pipeline)
python cli/structure.py --input ./books/ --output ./results/ --max-workers 5
```

**Pipeline Output**:
- Detailed JSON report in logs directory
- Stage-by-stage success rates
- File-level results with warnings and errors
- Performance metrics (time per file, tokens estimated)
- Issue categorization (topology errors, TOC mismatches, etc.)

### Implement New Processor

1. Create file in `processors/` (e.g., `translator.py`)
2. Implement processor class with `process()` method
3. Update `processors/__init__.py` to export it
4. Create CLI in `cli/` (e.g., `translate.py`)
5. Add entry point in `pyproject.toml` [project.scripts]
6. Add npm script in `package.json`
7. Update README.md roadmap

## File Organization

### Processors Module Structure
Each processor should follow this pattern:
```python
class ProcessorName:
    def __init__(self, **config):
        """Initialize with configuration"""

    def process(self, data: Dict) -> Dict:
        """Main processing method"""

    def process_file(self, input_path: str, output_path: str):
        """File-based processing"""

def main():
    """CLI entry point with argparse"""

if __name__ == "__main__":
    exit(main())
```

### CLI Module Structure
Each CLI should wrap a processor:
```python
#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from processors.module_name import main

if __name__ == "__main__":
    sys.exit(main())
```

## Testing Notes

Current test coverage is minimal (`tests/test_sanity.py` only).

When adding tests:
- Test each processor independently
- Mock AI API calls (don't hit real APIs in tests)
- Test edge cases: empty input, malformed JSON, large files
- Test chunking boundary conditions
- Test batch processing concurrency
- Validate output schema compliance

## Error Handling Patterns

### Retry Strategy (content_structurer.py)
- 3 attempts with 2s delay
- 300s timeout per request
- Mode-dependent: FLEXIBLE retries, STRICT fails fast
- Handles: JSON parse errors, validation failures, API failures

### Schema Validation
Checks:
- `content_blocks` array exists and non-empty
- Each block has: `id`, `type`, `content`, `metadata`
- Valid block types from predefined list
- IDs start with `block_`
- Non-empty content

### Batch Processing
- ThreadPoolExecutor catches individual failures
- Continues processing remaining files (unless STRICT mode)
- Returns: `{file: {status: "success|failed", result|error}}`

## Known Issues and Limitations

### Embedded First Chapter Pattern (Per Volume)

**Status**: ✅ **RESOLVED** - Now handled automatically by Stage 4 of batch processing pipeline

**Pattern**: First chapter of a volume embedded in title/introduction page

**Common in Chinese novels**: The first chapter of EACH volume is often embedded within what appears to be a title page or introduction section.

**Examples**:
- Volume 1: First chapter (typically "一、...") embedded in title page
- Volume 2: First chapter (could be "一、..." if reset, or "廿一、..." if continuing)
- Volume 3: First chapter (could be "三十一、...", "卅一、...", "一、..." depending on numbering scheme)

**Note**: Chapter numbering varies by work:
- Some reset to Chapter 1 per volume
- Some continue across volumes (Vol 1: 1-20, Vol 2: 21-40)
- Some have irregular numbering (Vol 3 might start at 31, not 41)

**Automatic Solution**: As of integration update, this is now handled automatically by:
- **Stage 4**: `utils/embedded_chapter_detector.py` in batch processing pipeline
- Runs automatically after JSON cleaning, before chapter alignment
- No manual intervention required

**Manual Solution** (if needed outside pipeline):
Use `scripts/fix_embedded_chapter1.py` standalone script to:
1. Extract first chapter from introduction/title page (regardless of chapter number)
2. Create proper chapter in body.chapters
3. Update TOC to include the extracted chapter
4. Clean introduction section (remove story content)

**Detection Capabilities**:
- ANY Chinese chapter markers (一、二、三... 廿、卅、卌... 第N章/回)
- Multiple possible intro locations (front_matter.introduction, front_matter.sections, etc.)
- Content boundaries between intro metadata and story content
- Works for any starting chapter number (not limited to Chapter 1)

**Multi-Volume Works**: Each volume file is processed separately, with automatic detection for each

### Chapter Alignment Fixer

**Issue**: Assumes books start at Chapter 1

**Problem**:
- The fixer in `utils/fix_chapter_alignment.py` assumes all books start at Chapter 1
- Some books (e.g., volume 3 of a series) start at Chapter 2 or higher
- This causes incorrect `chapter_number` fields in TOC entries

**Example**:
- Book: 羅剎夫人 (I0929) - Actually starts at 第二章 (Chapter 2)
- After processing: TOC shows 第一章 pointing to title page instead of first actual chapter
- Result: TOC chapter_number fields don't match actual chapter headings

**Workaround**:
- Sanity checker detects this as `nonstandard_start` issue (info severity)
- Validation stage may flag TOC/chapter mismatches
- Consider fixing the alignment fixer to detect and respect actual starting chapter

### Chinese Numeral Parsing

**Fixed**: Special numerals 廿 (20), 卅 (30), 卌 (40) now fully supported

**Historical Issue**:
- Before fix: 第廿一章 was parsed as 1 instead of 21
- Caused false duplicate chapter errors
- Fixed in `chapter_sequence_validator.py` with special case handling

### TOC Blob Parsing

**Edge Case**: Space-separated entries on single line

**Handling**:
- `restructure_toc.py` uses careful pattern matching
- Avoids over-splitting on internal spaces in chapter titles
- Supports both blob format and structured format

## Git Workflow

**IMPORTANT**: Git commits should ONLY be created when explicitly requested by the user.

- Do NOT create commits automatically after completing tasks
- Do NOT commit changes unless the user specifically asks you to
- Always ask the user if they want changes committed to git
- Wait for explicit confirmation before running git commands

When the user does request a commit, follow the standard git commit protocol as documented in the project guidelines.

## Current Status & Roadmap

**Implemented**:
- ✅ JSON Cleaner (raw JSON → structured blocks)
- ✅ Content Structurer (semantic classification)
- ✅ Batch Processing Pipeline (8-stage cleaning + validation)
- ✅ Translation Service (Classical Chinese → English with cultural footnotes)
- ✅ Translation Orchestration (7-stage pipeline with checkpoint/resume)
- ✅ Footnote Processing (4-phase: suppress → heuristics → AI scoring → context-free review, 93-98% junk removal)
- ✅ Validation Tools (TOC/chapter alignment, structure validation)

**In Progress**:
- 🚧 EPUB Builder (EPUB 3.0 generation, CSS themes, cover images)

**Future Enhancements**:
- Advanced formatting rules engine
- Multi-format output (PDF, MOBI)

**Source Files Location**: `/Users/jacki/project_files/translation_project/wuxia_individual_files`