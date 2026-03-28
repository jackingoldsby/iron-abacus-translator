# CLAUDE.md — Crimson Folio (丹帙)

**Crimson Folio** is the EPUB builder product. It takes translated JSON from Iron Abacus (stage 7 output) and produces Kindle-ready EPUB3 files with cover images, formatted chapters, popup footnotes, and glossary appendices.

## Architecture

```
crimson_folio/
├── builders/               # Core EPUB assembly
│   ├── epub_builder.py     # Main builder — JSON → EPUB3
│   ├── cover_page.py       # Cover image embedding
│   ├── chapter_renderer.py # Content blocks → XHTML (future per-theme)
│   └── glossary_renderer.py # Glossary grouping + rendering
│
├── covers/                 # Cover image pipeline (period artwork only)
│   ├── researcher.py       # DeepSeek: metadata → art search terms
│   ├── searcher.py         # Wikimedia Commons + Met Museum API search
│   ├── downloader.py       # Fetch + validate + cache images
│   └── composer.py         # Pillow: artwork + title overlay → cover
│
├── styles/                 # CSS themes
│   ├── kindle.css          # Default — Kindle Paperwhite/Oasis optimized
│   ├── modern.css          # Future: sans-serif modern theme
│   └── minimal.css         # Future: stripped-down reading theme
│
├── delivery/               # Distribution
│   ├── kindle_sender.py    # SMTP-based Kindle email delivery
│   └── send_to_kindle.py   # CLI for Kindle delivery
│
├── utils/                  # Shared utilities
│   ├── llm_client.py       # Lightweight DeepSeek client
│   └── catalog.py          # DuckDB catalog lookup (series, titles)
│
├── cli/                    # Entry points
│   └── build.py            # Main CLI: build EPUB from translated JSON
│
├── config/                 # Configuration
│   └── defaults.py         # Default paths, theme settings, image config
│
└── tests/
    └── test_epub_output.py # EPUB output validation tests
```

## Data Flow

```
Translated JSON (from iron_abacus stage 7)
    ↓
builders/epub_builder.py
    ├── Title page (bilingual)
    ├── Translator's preface
    ├── Chapters (popup footnotes, content-type formatting)
    ├── Glossary appendix (optional)
    └── Cover image (optional)
    ↓
EPUB 3.0 file (.epub)
    ↓
delivery/kindle_sender.py (optional)
    ↓
Kindle device
```

## Cover Image Pipeline

**IMPORTANT**: Cover images must be genuine period artwork — actual paintings,
scrolls, woodblock prints from the dynasty depicted in the novel. No modern
illustrations, no AI-generated images.

Pipeline steps:
1. **Research** (DeepSeek): Analyze book metadata → suggest period-specific art search queries
2. **Search** (Wikimedia Commons + Met Museum): Find public domain historical artworks
3. **Download**: Fetch + validate dimensions + cache locally
4. **Compose** (Pillow): Artwork background + title/author text overlay → EPUB cover

Cover cache: `~/.crimson_folio/covers/`

## Commands

```bash
cd crimson_folio

# Build EPUB from translated JSON
python -m cli.build --input /path/to/translated.json --output /path/to/book.epub

# Auto-name from metadata (Author - Title.epub)
python -m cli.build --input /path/to/translated.json

# Build with AI cover pipeline (searches for period artwork)
python -m cli.build --input /path/to/translated.json --cover

# Build with specific cover image
python -m cli.build --input /path/to/translated.json --cover-image /path/to/art.jpg

# Send EPUB to Kindle
python -m delivery.send_to_kindle /path/to/book.epub
python -m delivery.send_to_kindle /path/to/book.epub --dry-run

# Run tests
pytest tests/
```

## Input Contract

Crimson Folio consumes translated JSON from Iron Abacus stage 7. Required structure:

```json
{
  "meta": {
    "work_number": "D1379",
    "title": "偷拳",
    "author": "白羽",
    "translation": { "title": "The Stolen Fist", "author": "Bai Yu" }
  },
  "structure": {
    "body": {
      "chapters": [{
        "id": "chapter_001",
        "title_english": "Chapter 1: ...",
        "title_chinese": "第一回 ...",
        "content_blocks": [{
          "id": "block_0001",
          "type": "paragraph",
          "content": "Chinese original",
          "translated_content": "English with [1] markers",
          "content_type": "narrative|dialogue|verse|document|thought",
          "footnotes": [{
            "key": 1,
            "ideogram": "經脈",
            "pinyin": "jīngmài",
            "explanation": "Meridian channels..."
          }]
        }]
      }]
    }
  }
}
```

## Key Design Decisions

- **No cross-imports**: Does not import from iron_abacus or jade_shuttle
- **Own catalog client**: `utils/catalog.py` queries DuckDB directly
- **Own LLM client**: `utils/llm_client.py` for DeepSeek cover research only
- **Footnote renumbering at build time**: Chapter-level sequential numbering happens in epub_builder, not as a pre-processing step
- **Period art only**: Cover pipeline enforces genuine historical artwork

## Dependencies

See `requirements.txt`:
- `ebooklib` — EPUB3 file generation
- `Pillow` — Cover image composition
- `openai` — DeepSeek client (OpenAI-compatible API)
- `python-dotenv` — Environment variable loading
- `requests` — HTTP for image search/download
- `duckdb` — Catalog database access

## Environment

API keys loaded from `.env` (checked in order):
1. `crimson_folio/.env`
2. Workspace root `.env`
3. `iron_abacus_translator/.env`

Required for cover pipeline: `DEEPSEEK_API_KEY`
Required for Kindle delivery: `KINDLE_EMAILS`, `SMTP_USER`, `SMTP_PASSWORD`
