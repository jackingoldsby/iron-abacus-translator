# Iron Abacus Translator

Classical Chinese literature translation pipeline — from raw JSON through cleaning, AI structuring, translation with cultural footnotes, to final EPUB generation.

## Vision

```
Raw JSON → Clean → Structure → Translate → Footnotes → EPUB
```

### Current Status

- ✅ **JSON Cleaner** — Transform raw book JSON into discrete content blocks
- ✅ **Post-Processing Tools** — Chapter alignment, TOC restructuring, embedded chapter detection
- ✅ **Validation Tools** — Sanity checker, sequence validator, TOC alignment validator
- ✅ **Content Structurer** — AI-powered semantic analysis (narrative, dialogue, verse, etc.)
- ✅ **Translator** — Classical Chinese → English with cultural/historical footnotes
- ✅ **Footnote Processing** — 4-phase pipeline (suppress list → heuristics → AI scoring → context-free review)
- 🚧 **EPUB Builder** — In progress

## Quick Start

### Installation

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Usage

```bash
# 1. Clean JSON (no API required)
python cli/clean.py --input book.json --output-dir ./output --language zh-Hant

# 2. Batch processing (8-stage pipeline)
python scripts/batch_process_books.py \
  --source-dir ./source_files \
  --output-dir ./output \
  --catalog-path ./catalog.db

# 3. Translation (8-stage pipeline with footnotes)
python scripts/translate_work.py D1379
python scripts/translate_work.py D1379 --volume a    # specific volume
python scripts/translate_work.py D1379 --resume       # resume from checkpoint

# 4. Discovery UI (Streamlit)
streamlit run app_discover.py
```

## Environment Variables

```bash
export OPENAI_API_KEY=your-openai-key       # Required for AI features
export ANTHROPIC_API_KEY=your-anthropic-key  # Optional alternative
```

Copy `.env.example` to `.env` and fill in your keys.

## Project Structure

```
iron-abacus-translator/
├── processors/              # Pipeline processors
│   ├── json_cleaner.py         Clean raw JSON → discrete blocks
│   ├── content_structurer.py   AI semantic classification
│   ├── translator.py           Classical Chinese translation
│   ├── book_translator.py      Book-level translation orchestration
│   └── epub_builder.py         EPUB generation (in progress)
│
├── utils/                   # Processing utilities
│   ├── remove_trivial_footnotes.py  4-phase footnote cleanup
│   ├── topology_analyzer.py         Structure analysis
│   ├── sanity_checker.py            Early validation + metadata
│   ├── fix_chapter_alignment.py     Fix chapter titles
│   ├── restructure_toc.py           Structured TOC
│   ├── embedded_chapter_detector.py Detect/extract embedded chapters
│   ├── clients/                     API client wrappers
│   └── db.py                        DuckDB catalog access
│
├── scripts/                 # Pipeline entry points
│   ├── batch_process_books.py    8-stage cleaning pipeline
│   └── translate_work.py         Translation orchestration
│
├── config/                  # Configuration files
│   └── wuxia_suppress_list.json  Footnote suppress list (100+ terms)
│
├── cli/                     # Command-line interfaces
├── wrappers/                # Translation wrappers
├── workflows/               # DAG workflow engine
├── web_ui/                  # Translation manager UI
├── docs/                    # Documentation
└── tests/                   # Test suite
```

## Documentation

- **[CLAUDE.md](CLAUDE.md)** — Architecture guide and pipeline details
- **[docs/BEST_PRACTICES.md](docs/BEST_PRACTICES.md)** — Coding conventions and standards
- **[docs/translation/](docs/translation/)** — Translation pipeline documentation

## License

MIT
