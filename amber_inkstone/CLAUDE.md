# CLAUDE.md — Amber Inkstone (琥珀硯)

**Amber Inkstone** is the period artwork portfolio curator. It groups works by dynasty, researches art context via DeepSeek, searches museum APIs for genuine period artwork, downloads and caches images, and lets the user assign images to works for EPUB cover use.

## Architecture

```
amber_inkstone/
├── catalog/                  # Work grouping + portfolio storage
│   ├── period_grouper.py     # Group works by dynasty from DuckDB catalog
│   └── portfolio_db.py       # Portfolio metadata CRUD (artwork_portfolio.duckdb)
│
├── research/                 # DeepSeek-powered art context
│   ├── period_researcher.py  # Dynasty art styles, subjects, media
│   └── query_generator.py    # Period context → search queries
│
├── sources/                  # Museum API search
│   ├── base.py               # BaseSource ABC
│   ├── wikimedia.py          # Wikimedia Commons (reject modern/AI)
│   ├── met_museum.py         # Met Museum Open Access
│   └── registry.py           # Source dispatch
│
├── acquisition/              # Image download + validation
│   ├── downloader.py         # Fetch + cache + thumbnail
│   └── validator.py          # Image validation (size, format, aspect)
│
├── models/
│   └── portfolio.py          # PeriodGroup, ArtworkCandidate, ArtworkImage, etc.
│
├── config/
│   ├── defaults.py           # Paths, cache dirs, image settings
│   └── dynasty_periods.py    # Hardcoded dynasty dates + artist whitelists
│
├── utils/
│   └── llm_client.py         # DeepSeek client
│
├── cli/
│   ├── curate.py             # Build/refresh portfolio by period
│   ├── browse.py             # Browse portfolio (terminal table)
│   └── assign.py             # Manage image→work assignments
│
└── tests/
    ├── test_period_grouper.py
    └── test_portfolio_db.py
```

## Data Flow

```
DuckDB catalog (works.setting_period, series.historical_period)
    → period_grouper.py (normalize to canonical slugs)
    → period_researcher.py (DeepSeek: art styles, subjects, media)
    → query_generator.py (period context + artist whitelist → search queries)
    → wikimedia.py + met_museum.py (API search → ArtworkCandidate)
    → downloader.py (fetch + validate + cache + thumbnail)
    → portfolio_db.py (store in artwork_portfolio.duckdb)
    → User browses + assigns image to work
    → crimson_folio --cover-image /path/to/cached/image.jpg
```

## Anti-Hallucination Strategy

1. **Dynasty dates hardcoded** in `config/dynasty_periods.py` — DeepSeek does NOT provide dates
2. **Prompt constraints**: DeepSeek provides art styles, subjects, media — NOT specific artwork titles or catalog numbers
3. **Artist whitelist**: Only verified historical artists used as primary search terms
4. **API results are source of truth**: Only artwork from Wikimedia/Met enters the portfolio
5. **Research cached**: One DeepSeek call per period, stored in DB

## Commands

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

## Key Design Decisions

- **No cross-imports**: Does not import from iron_abacus, jade_shuttle, or crimson_folio
- **Period-level, not per-book**: Research and search happen per dynasty, not per novel
- **Own LLM client**: `utils/llm_client.py` for DeepSeek research only
- **Only genuine period artwork**: Modern/AI/photograph rejection filters in Wikimedia source
- **Manual assignment**: User browses portfolio and assigns images; no automatic cover selection

## Image Cache

```
~/.amber_inkstone/images/
├── ming_dynasty/
│   ├── abc123def456.jpg
│   ├── abc123def456_thumb.jpg
│   └── ...
├── song_dynasty/
└── ...
```

## Portfolio Database

`/Users/jacki/project_files/translation_project/db/artwork_portfolio.duckdb`

Tables: `artwork_images`, `artwork_assignments`, `period_research_cache`

## Dependencies

See `requirements.txt`:
- `Pillow` — Image validation + thumbnails
- `openai` — DeepSeek client (OpenAI-compatible API)
- `python-dotenv` — Environment variable loading
- `requests` — HTTP for API search + download
- `duckdb` — Portfolio database
- `rich` — Terminal table display (optional, fallback to plain text)

## Environment

API keys loaded from `.env` (checked in order):
1. `amber_inkstone/.env`
2. Workspace root `.env`
3. `iron_abacus_translator/.env`

Required: `DEEPSEEK_API_KEY`
