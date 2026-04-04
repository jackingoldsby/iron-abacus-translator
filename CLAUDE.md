# CLAUDE.md — Workspace Root

This is the **agentic workspace** for eleven independent products: Iron Abacus (translation), Jade Shuttle (extraction), Crimson Folio (EPUB generation), Amber Inkstone (period artwork curation), Azure Register (catalog enrichment), Silver Gauge (column detection & strip slicing), Bronze Mirror (strip OCR), Platinum Scale (strip validation via nano), Ivory Helm (iterative OCR orchestration), Cobalt Loom (Wikisource/ctext.org scraping), and Vermilion Brush (scanned PDF OCR — legacy).

## Workspace Structure

```
agentic_test_project/                    # GIT ROOT / WORKSPACE
├── .claude/agents/                      # Agent definitions (dev tooling)
├── CLAUDE.md                            # THIS FILE — workspace guidance
├── docs/BEST_PRACTICES.md              # Dev standards
│
├── iron_abacus_translator/              # TRANSLATION PIPELINE PRODUCT
│   ├── CLAUDE.md                        # Pipeline architecture & commands (THE source of truth)
│   ├── processors/                      # Translation, cleaning, structuring
│   ├── utils/                           # Validators, glossary, environment config
│   ├── cli/                             # CLI entry points
│   ├── config/                          # Suppress lists, translation rules
│   ├── scripts/                         # Production scripts (orchestration, batch processing)
│   ├── wrappers/                        # Translation wrappers
│   ├── workflows/                       # DAG engine
│   ├── web_ui/                          # Translation manager UI
│   ├── ai/                              # Assistant manager
│   ├── tests/                           # Pipeline tests
│   └── docs/                            # Pipeline documentation
│
├── jade_shuttle/                        # EBOOK EXTRACTION PRODUCT
│   ├── CLAUDE.md                        # Extraction architecture (source of truth)
│   ├── extractors/                      # Format-specific parsers (EPUB, future: PDF, TXT)
│   ├── detectors/                       # TOC, work, volume, chapter detection
│   ├── transformers/                    # HTML→blocks, encoding, JSON emission
│   ├── catalog/                         # DuckDB dedup and registration
│   ├── models/                          # Shared data models
│   ├── config/                          # Authors, skip patterns, defaults
│   ├── cli/                             # CLI entry points
│   └── tests/                           # Extraction tests
│
├── crimson_folio/                       # EPUB GENERATION PRODUCT (丹帙)
│   ├── CLAUDE.md                        # EPUB builder architecture (source of truth)
│   ├── builders/                        # EPUB3 assembly (epub_builder, cover, glossary)
│   ├── covers/                          # Cover image composition (composer only)
│   ├── styles/                          # CSS themes (kindle, modern, minimal)
│   ├── delivery/                        # Kindle email delivery
│   ├── utils/                           # LLM client, catalog lookup
│   ├── cli/                             # CLI entry points
│   ├── config/                          # Default paths, settings
│   └── tests/                           # EPUB output tests
│
├── amber_inkstone/                      # PERIOD ARTWORK CURATOR (琥珀硯)
│   ├── CLAUDE.md                        # Portfolio architecture (source of truth)
│   ├── catalog/                         # Period grouping + portfolio DB
│   ├── research/                        # DeepSeek art context research
│   ├── sources/                         # Wikimedia Commons + Met Museum search
│   ├── acquisition/                     # Image download + validation
│   ├── models/                          # Data models
│   ├── config/                          # Dynasty periods, defaults
│   ├── utils/                           # DeepSeek LLM client
│   ├── cli/                             # curate, browse, assign
│   └── tests/                           # Portfolio tests
│
├── azure_register/                      # CATALOG ENRICHMENT PRODUCT (蒼籍)
│   ├── CLAUDE.md                        # Enrichment architecture (source of truth)
│   ├── enrichers/                       # Library, reader, CSV enrichment logic
│   ├── prompts/                         # DeepSeek prompt templates
│   ├── schema/                          # DB schema migrations
│   ├── utils/                           # DeepSeek LLM client, DB connector
│   ├── config/                          # Default paths, batch sizes
│   ├── cli/                             # enrich (library/reader/csv/status)
│   └── tests/                           # Enrichment tests
│
├── silver_gauge/                        # COLUMN DETECTION & STRIP SLICING (銀規)
│   ├── CLAUDE.md                        # Detection architecture (source of truth)
│   ├── detectors/                       # Column detection, validation, slicing, classification
│   ├── extractors/                      # PDF→images, image preprocessing
│   ├── config/                          # DPI, thresholds, output paths
│   ├── cli/                             # slice
│   ├── scripts/                         # Batch slicing
│   └── tests/                           # Detection tests
│
├── platinum_scale/                      # STRIP VALIDATION VIA NANO (鉑秤)
│   ├── CLAUDE.md                        # Validation architecture (source of truth)
│   ├── validators/                      # gpt-4.1-nano vision strip classification
│   ├── config/                          # Model, cost, concurrency settings
│   ├── cli/                             # validate
│   ├── scripts/                         # Batch validation
│   └── tests/                           # Validation tests
│
├── bronze_mirror/                       # STRIP OCR PRODUCT (銅鏡)
│   ├── CLAUDE.md                        # OCR architecture (source of truth)
│   ├── ocr/                             # PaddleOCR engine, postprocessor
│   ├── readers/                         # Strip reader (page/book OCR with resume)
│   ├── structurers/                     # Page classification, hui detection, JSON emission
│   ├── config/                          # OCR settings, output paths
│   ├── cli/                             # read
│   ├── scripts/                         # Batch OCR, validation
│   └── tests/                           # OCR tests
│
├── ivory_helm/                          # ITERATIVE OCR ORCHESTRATOR (象牙舵)
│   ├── CLAUDE.md                        # Orchestration architecture (source of truth)
│   ├── orchestrator/                    # Iteration loop: slice→OCR→validate→assess
│   ├── config/                          # Thresholds, re-slice strategies
│   ├── cli/                             # run, report
│   └── tests/                           # Orchestration tests
│
├── cobalt_loom/                          # WIKISOURCE / CTEXT SCRAPER (鈷織機)
│   ├── CLAUDE.md                        # Scraper architecture (source of truth)
│   ├── scrapers/                        # Wikisource (MediaWiki API) + ctext.org (HTML)
│   ├── structurers/                     # HTML→blocks, chapter detection, JSON emission
│   ├── catalog/                         # DuckDB lookup + registration
│   ├── cache/                           # File-based HTML cache
│   ├── models/                          # Data models
│   ├── config/                          # Defaults, work URL mapping
│   ├── cli/                             # list, scrape, status
│   └── tests/                           # Scraper tests
│
├── vermilion_brush/                     # SCANNED PDF OCR — LEGACY (朱筆)
│   ├── CLAUDE.md                        # OCR architecture (source of truth)
│   ├── extractors/                      # PDF→images, image preprocessing
│   ├── ocr/                             # PaddleOCR engine, vertical column reordering
│   ├── structurers/                     # Page classification, hui detection, JSON emission
│   ├── config/                          # DPI, model paths, output paths
│   ├── cli/                             # scan, preview, check
│   └── tests/                           # OCR tests
│
├── dev/                                 # DEV TOOLING (not part of any product)
│   ├── test/                            # Test scripts (test_chapter1, test_glossary, etc.)
│   ├── demo/                            # Demo scripts (glossary matching demos)
│   ├── eval/                            # Evaluation scripts (prompt version comparison)
│   ├── admin/                           # Admin scripts (migration, catalog, ingestion)
│   ├── autonomous_test_and_fix.py       # Autonomous test runner
│   └── app_discover.py                  # Streamlit discovery UI
│
└── translation_data -> /Users/jacki/project_files/translation_project/translation_data
```

## Key Principle

**Eleven products**: `iron_abacus_translator/` (translation), `jade_shuttle/` (extraction), `crimson_folio/` (EPUB generation), `amber_inkstone/` (period artwork curation), `azure_register/` (catalog enrichment), `silver_gauge/` (column detection & strip slicing), `platinum_scale/` (strip validation via nano), `bronze_mirror/` (strip OCR), `cobalt_loom/` (web scraping), and `vermilion_brush/` (legacy OCR). They communicate through JSON files and shared DuckDB databases. **No product imports from another.**

- jade_shuttle uses **no LLMs** — purely deterministic extraction
- iron_abacus_translator uses **OpenAI and DeepSeek** for translation
- crimson_folio uses **DeepSeek** for cover art composition only
- amber_inkstone uses **DeepSeek** for dynasty art research, searches Wikimedia/Met Museum APIs
- azure_register uses **DeepSeek** for catalog metadata enrichment (factual + reader-oriented)
- silver_gauge uses **no LLMs** — purely deterministic CV (column detection, strip slicing)
- platinum_scale uses **OpenAI gpt-4.1-nano** — vision-based strip validation (~$0.01/chapter)
- bronze_mirror uses **no LLMs** — local PaddleOCR models only (strip OCR)
- ivory_helm uses **OpenAI gpt-4.1-nano** (via Platinum Scale) — iterative orchestration of slice→OCR→validate
- cobalt_loom uses **no LLMs** — deterministic web scraping (Wikisource MediaWiki API + ctext.org via Nimble SDK)
- vermilion_brush uses **no LLMs** — legacy, replaced by ivory_helm (silver_gauge + bronze_mirror + platinum_scale)
- Claude's role is as the **developer** of all eleven products, operating from this workspace
- For iron_abacus architecture: **see `iron_abacus_translator/CLAUDE.md`**
- For jade_shuttle architecture: **see `jade_shuttle/CLAUDE.md`**
- For crimson_folio architecture: **see `crimson_folio/CLAUDE.md`**
- For amber_inkstone architecture: **see `amber_inkstone/CLAUDE.md`**
- For azure_register architecture: **see `azure_register/CLAUDE.md`**
- For silver_gauge architecture: **see `silver_gauge/CLAUDE.md`**
- For platinum_scale architecture: **see `platinum_scale/CLAUDE.md`**
- For bronze_mirror architecture: **see `bronze_mirror/CLAUDE.md`**
- For ivory_helm architecture: **see `ivory_helm/CLAUDE.md`**
- For cobalt_loom architecture: **see `cobalt_loom/CLAUDE.md`**
- For vermilion_brush architecture: **see `vermilion_brush/CLAUDE.md`** (legacy)
- For coding standards: **see `docs/BEST_PRACTICES.md`**

## Data Flow

```
Scanned PDFs  →  ivory_helm [ silver_gauge (slice) → bronze_mirror (OCR) → platinum_scale (validate) ⟳ ]  →  raw JSON  →  iron_abacus_translator  →  translated JSON  →  crimson_folio  →  EPUB file
EPUB files    →  jade_shuttle                                              →  raw JSON  ↗                                                      ↕
Web sources   →  cobalt_loom (Wikisource / ctext.org)                      →  raw JSON  ↗                                               DuckDB catalog
                                                                                 ↕                                                      DuckDB catalog
                                                                         DuckDB catalog  ←──  azure_register (enrichment)
                                                                                 ↕                     ↕
                                                                         amber_inkstone  →  artwork_portfolio.duckdb  →  --cover-from-portfolio
                                                                                 ↕
                                                                         DeepSeek (art research)
                                                                         Wikimedia + Met Museum APIs
```

Silver Gauge detects and slices columns from scanned PDFs into persistent strip images. Bronze Mirror OCRs those strips and emits raw JSON. Jade Shuttle parses EPUBs. Cobalt Loom scrapes Wikisource/ctext.org. All three produce raw JSON. Iron Abacus translates it. Azure Register enriches the catalog with factual and reader-oriented metadata via DeepSeek. Amber Inkstone curates period artwork portfolios by dynasty. Crimson Folio renders EPUBs, using either direct image paths or portfolio-assigned covers. The DuckDB catalog (`works_translator.duckdb`) is shared state for deduplication, series metadata, enrichment, and work tracking.

## LLM Provider Concurrency

Both **DeepSeek** and **OpenAI** support up to **50 parallel workers**. When writing code that calls LLMs, parallelize by default. Only use sequential LLM calls when there is a logical dependency (e.g. a later prompt requires the output of an earlier one).

## External Services

### Nimble SDK (web extraction)
- **Used by**: cobalt_loom (ctext.org scraping with anti-bot bypass)
- **SDK**: `nimble-python` — `pip install nimble-python`
- **API key**: Set `NIMBLE_API_TOKEN` in `.env` files
- **Drivers**: `vx6` (fast HTTP), `vx10` (stealth headless — used for ctext.org)
- **Docs**: See `docs/nimble_docs.md` for full Extract API reference
- **Fallback**: If Nimble is unavailable, cobalt_loom falls back to direct httpx requests

## Running Pipeline Commands

### Iron Abacus (translation)

```bash
cd iron_abacus_translator

# Translation orchestration (DAG pipeline)
python -m cli.run_pipeline D1379
python -m cli.run_pipeline D1379 --resume
python -m cli.run_pipeline D1379 --from cleanup_6a

# Batch processing
python scripts/batch_process_books.py --source-dir /path/to/source --output-dir /path/to/output --catalog-path /path/to/catalog.duckdb

# Individual processors
python cli/clean.py --input book.json --output cleaned.json
python cli/structure.py --input cleaned.json --output structured.json

# Tests
pytest tests/test_sanity.py
```

### Jade Shuttle (extraction)

```bash
cd jade_shuttle

# Dry run — detect works without writing
python -m cli.ingest --dry-run

# Process a single EPUB
python -m cli.ingest --single "萧逸*.epub" --dry-run

# Full ingestion
python -m cli.ingest

# With report
python -m cli.ingest --report /tmp/ingest_report.json
```

### Crimson Folio (EPUB generation)

```bash
cd crimson_folio

# Build EPUB from translated JSON
python -m cli.build --input /path/to/translated.json --output book.epub
python -m cli.build --input /path/to/translated.json  # auto-names from metadata

# Build with AI-researched period artwork cover (legacy)
python -m cli.build --input /path/to/translated.json --cover

# Build with specific cover image
python -m cli.build --input /path/to/translated.json --cover-image /path/to/art.jpg

# Build with portfolio-assigned cover (from amber_inkstone)
python -m cli.build --input /path/to/translated.json --cover-from-portfolio

# Send to Kindle
python -m delivery.send_to_kindle /path/to/book.epub
python -m delivery.send_to_kindle /path/to/book.epub --dry-run

# Tests
pytest tests/
```

### Amber Inkstone (period artwork)

```bash
cd amber_inkstone

# List period groups from catalog
python -m cli.curate --list-periods

# Build portfolio for one period
python -m cli.curate --period "Ming Dynasty" --limit 20

# Dry run — show queries without downloading
python -m cli.curate --period "Ming Dynasty" --dry-run

# Build for all periods
python -m cli.curate --all --limit 10

# Browse portfolio
python -m cli.browse
python -m cli.browse --period "Ming Dynasty"

# Assign image to work
python -m cli.assign --work D1379 --image ~/.amber_inkstone/images/ming_dynasty/abc123.jpg
python -m cli.assign --list
python -m cli.assign --work D1379 --clear
```

### Azure Register (catalog enrichment)

```bash
cd azure_register

# Library enrichment (factual metadata via DeepSeek)
python -m cli.enrich library --dry-run
python -m cli.enrich library --limit 5 --diff
python -m cli.enrich library --author "Jin Yong" --unenriched-only

# Reader enrichment (subjective metadata via DeepSeek)
python -m cli.enrich reader --dry-run
python -m cli.enrich reader --limit 10 --diff
python -m cli.enrich reader --unenriched-only

# CSV import
python -m cli.enrich csv --csv /path/to/works.csv

# Enrichment status
python -m cli.enrich status
```

### Cobalt Loom (web scraping)

```bash
cd cobalt_loom

# List works needing scraping
python -m cli.scrape list

# Dry run — discover chapters, no downloads
python -m cli.scrape scrape --work A005 --dry-run

# Scrape one work
python -m cli.scrape scrape --work A005

# Scrape all unscraped works
python -m cli.scrape scrape --all

# Resume (skip already-scraped chapters)
python -m cli.scrape scrape --work A005 --resume

# Show progress
python -m cli.scrape status
```

### Silver Gauge (column detection & strip slicing)

```bash
cd /path/to/workspace

# Slice a single PDF
python -m silver_gauge.cli.slice --pdf /path/to/vol1.pdf --output-dir /path/to/strips/

# Slice specific page range
python -m silver_gauge.cli.slice --pdf /path/to/vol1.pdf --pages 80-97 --output-dir /path/to/strips/

# Slice all PDFs in a directory
python -m silver_gauge.cli.slice --dir /path/to/三俠五義_俞平伯校點本/ --output-dir /path/to/strips/

# Dry run — show detection stats, no writes
python -m silver_gauge.cli.slice --pdf /path/to/vol1.pdf --dry-run
```

### Platinum Scale (strip validation)

```bash
cd /path/to/workspace

# Validate all strips via nano vision
python -m platinum_scale.cli.validate --strips-dir /path/to/ocr_strips/三俠五義_validation/

# Resume (skip already-validated pages)
python -m platinum_scale.cli.validate --strips-dir /path/to/strips/ --resume

# Show validation report (no API calls)
python -m platinum_scale.cli.validate --strips-dir /path/to/strips/ --report

# Show Silver Gauge vs nano disagreements
python -m platinum_scale.cli.validate --strips-dir /path/to/strips/ --show-disagreements
```

### Bronze Mirror (strip OCR)

```bash
cd /path/to/workspace

# OCR a sliced book
python -m bronze_mirror.cli.read --strips-dir /path/to/ocr_strips/三俠五義/ --output /path/to/raw.json

# Resume interrupted OCR
python -m bronze_mirror.cli.read --strips-dir /path/to/ocr_strips/三俠五義/ --output /path/to/raw.json --resume

# OCR specific pages
python -m bronze_mirror.cli.read --strips-dir /path/to/ocr_strips/三俠五義/ --pages 80-97

# Show failed strips
python -m bronze_mirror.cli.read --strips-dir /path/to/ocr_strips/三俠五義/ --show-failures

# Validate chapter 1 (runs both silver_gauge + bronze_mirror)
python bronze_mirror/scripts/validate_chapter1.py
```

### Ivory Helm (iterative OCR orchestration)

```bash
cd /path/to/workspace

# Run iterative pipeline: slice → OCR → validate → re-slice if needed
python -m ivory_helm.cli.run run --strips-dir /path/to/strips/ --images-dir /path/to/page_images/

# Resume (skip pages that already passed)
python -m ivory_helm.cli.run run --strips-dir /path/to/strips/ --images-dir /path/to/images/ --resume

# Show iteration results
python -m ivory_helm.cli.run report --strips-dir /path/to/strips/
```

### Vermilion Brush (scanned PDF OCR — legacy)

```bash
cd vermilion_brush

# Preview OCR on a few pages
python -m cli.ocr preview --pdf /path/to/vol1.pdf --pages 5-10

# Check accuracy on a single page
python -m cli.ocr check --pdf /path/to/vol1.pdf --page 30

# Dry run — show page classification + detected chapters
python -m cli.ocr scan --dir /path/to/三俠五義_俞平伯校點本/ --dry-run

# Full scan to JSON
python -m cli.ocr scan --dir /path/to/三俠五義_俞平伯校點本/ --output /path/to/raw.json

# Single PDF
python -m cli.ocr scan --pdf /path/to/vol1_part1.pdf --output /tmp/test.json
```

## Running Dev Scripts

Dev scripts resolve their own paths via `sys.path.insert`:

```bash
# From workspace root
python dev/test/test_glossary_translation.py
python dev/demo/demo_glossary_simple.py
python dev/eval/eval_prompt_version.py
streamlit run dev/app_discover.py
```

## Agent Delegation

Agent definitions live in `.claude/agents/`:
- Iron Abacus agents reference paths prefixed with `iron_abacus_translator/`
- The `extractor-builder` agent works with `jade_shuttle/`
- The `epub-builder` agent works with `crimson_folio/`
- See each product's `CLAUDE.md` for details

## Environment

**API keys** are stored in `.env` files (NOT shell environment variables):
- `iron_abacus_translator/.env` — canonical location for all API keys
- `.env` (workspace root) — symlink/copy, also has keys

**IMPORTANT**: When writing scripts that call LLM APIs, always load dotenv:
```python
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / "iron_abacus_translator" / ".env")
# Or for scripts inside iron_abacus_translator/:
load_dotenv(Path(__file__).resolve().parent / ".env")
```

Do NOT rely on shell-exported environment variables — they may be stale or missing.

```bash
# Pipeline venv (shared by both products)
cd iron_abacus_translator
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r ../jade_shuttle/requirements.txt
pip install -r ../crimson_folio/requirements.txt
pip install -r ../amber_inkstone/requirements.txt
pip install -r ../azure_register/requirements.txt
pip install -r ../silver_gauge/requirements.txt
pip install -r ../platinum_scale/requirements.txt
pip install -r ../bronze_mirror/requirements.txt
pip install -r ../ivory_helm/requirements.txt
pip install -r ../cobalt_loom/requirements.txt
pip install -r ../vermilion_brush/requirements.txt
```

## Source Data

EPUB sources: `/Users/jacki/project_files/translation_project/for_parsing/`
Raw JSON files: `/Users/jacki/project_files/translation_project/work_individual_files/`
Translation output: `/Users/jacki/project_files/translation_project/translation_data/`

These paths are NOT in the repo — they're on the local filesystem.

## Databases

The pipeline uses **local DuckDB** files (not MotherDuck or any remote database):

```
/Users/jacki/project_files/translation_project/db/
├── works_translator.duckdb    # Work catalog: titles, authors, series, enrichment metadata
├── pipeline_progress.duckdb   # DAG pipeline: per-stage progress tracking per work/volume
├── glossary.duckdb            # Glossary data
└── artwork_portfolio.duckdb   # Amber Inkstone: artwork images, assignments, research cache
```

These are local files — connect with `duckdb.connect(path)` directly, no network required.

## Git Workflow

**IMPORTANT**: Git commits should ONLY be created when explicitly requested by the user.
