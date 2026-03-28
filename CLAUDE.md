# CLAUDE.md — Workspace Root

This is the **agentic workspace** for two independent products: Iron Abacus (translation) and Jade Shuttle (extraction).

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
├── dev/                                 # DEV TOOLING (not part of either product)
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

**Two products**: `iron_abacus_translator/` (translation pipeline) and `jade_shuttle/` (ebook extraction). They communicate through raw JSON files and the shared DuckDB catalog. **Neither imports from the other.**

- Both products use **no LLMs at extraction time** — jade_shuttle is purely deterministic
- iron_abacus_translator uses **OpenAI and DeepSeek** for translation
- Claude's role is as the **developer** of both products, operating from this workspace
- For iron_abacus architecture: **see `iron_abacus_translator/CLAUDE.md`**
- For jade_shuttle architecture: **see `jade_shuttle/CLAUDE.md`**
- For coding standards: **see `docs/BEST_PRACTICES.md`**

## Data Flow

```
EPUB files  →  jade_shuttle  →  raw JSON  →  iron_abacus_translator  →  translated EPUB
                                    ↕
                            DuckDB catalog
```

Jade Shuttle produces raw JSON in the contract format. Iron Abacus consumes it. The DuckDB catalog (`works_translator.duckdb`) is shared state for deduplication and work tracking.

## LLM Provider Concurrency

Both **DeepSeek** and **OpenAI** support up to **50 parallel workers**. When writing code that calls LLMs, parallelize by default. Only use sequential LLM calls when there is a logical dependency (e.g. a later prompt requires the output of an earlier one).

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
```

## Source Data

EPUB sources: `/Users/jacki/project_files/translation_project/for_parsing/`
Raw JSON files: `/Users/jacki/project_files/translation_project/wuxia_individual_files/`
Translation output: `/Users/jacki/project_files/translation_project/translation_data/`

These paths are NOT in the repo — they're on the local filesystem.

## Databases

The pipeline uses **local DuckDB** files (not MotherDuck or any remote database):

```
/Users/jacki/project_files/translation_project/db/
├── works_translator.duckdb    # Work catalog: titles, authors, series, enrichment metadata
├── pipeline_progress.duckdb   # DAG pipeline: per-stage progress tracking per work/volume
└── glossary.duckdb            # Glossary data
```

These are local files — connect with `duckdb.connect(path)` directly, no network required.

## Git Workflow

**IMPORTANT**: Git commits should ONLY be created when explicitly requested by the user.
