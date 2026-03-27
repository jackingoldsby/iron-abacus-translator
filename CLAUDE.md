# CLAUDE.md — Workspace Root

This is the **agentic workspace** that wraps the Iron Abacus Translator pipeline.

## Workspace Structure

```
agentic_test_project/                    # GIT ROOT / WORKSPACE
├── .claude/agents/                      # Agent definitions (dev tooling)
├── CLAUDE.md                            # THIS FILE — workspace guidance
├── docs/BEST_PRACTICES.md              # Dev standards
│
├── iron_abacus_translator/              # THE PIPELINE PRODUCT
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
├── dev/                                 # DEV TOOLING (not part of the product)
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

**iron_abacus_translator/ is the product. Everything else is dev tooling.**

- Pipeline code lives exclusively in `iron_abacus_translator/`
- For pipeline architecture, commands, and implementation details: **see `iron_abacus_translator/CLAUDE.md`**
- For coding standards: **see `docs/BEST_PRACTICES.md`**

## Running Pipeline Commands

All pipeline commands must run from within the iron_abacus_translator directory:

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

## Running Dev Scripts

Dev scripts resolve their own paths to `iron_abacus_translator/` via `sys.path.insert`:

```bash
# From workspace root
python dev/test/test_glossary_translation.py
python dev/demo/demo_glossary_simple.py
python dev/eval/eval_prompt_version.py
streamlit run dev/app_discover.py
```

## Agent Delegation

Agent definitions live in `.claude/agents/` and reference pipeline paths prefixed with `iron_abacus_translator/`. See `iron_abacus_translator/CLAUDE.md` for the full agent delegation guide.

## Environment

```bash
# Required
export OPENAI_API_KEY=your-key-here
export ANTHROPIC_API_KEY=your-key-here  # Optional

# Pipeline venv
cd iron_abacus_translator
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Source Data

Source files: `/Users/jacki/project_files/translation_project/wuxia_individual_files`
Translation output: `/Users/jacki/project_files/translation_project/translation_data/`

These paths are NOT in the repo — they're on the local filesystem.

## Git Workflow

**IMPORTANT**: Git commits should ONLY be created when explicitly requested by the user.
