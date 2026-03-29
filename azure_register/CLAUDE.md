# CLAUDE.md -- Azure Register (蒼籍)

**Azure Register** is the catalog enrichment product. It enriches the shared DuckDB catalog (`works_translator.duckdb`) with factual, reader-oriented, and CSV-sourced metadata using DeepSeek.

## Architecture

```
azure_register/
├── enrichers/                 # Core enrichment logic
│   ├── base.py                # BaseEnricher: shared DB, batching, diff, change computation
│   ├── library.py             # LibraryEnricher: factual metadata via DeepSeek
│   ├── reader.py              # ReaderEnricher: reader-oriented metadata via DeepSeek
│   ├── csv_loader.py          # CsvEnricher: CSV-to-DB import
│   └── _status_sync.py        # Sync enriched fields to status.json files
│
├── prompts/                   # DeepSeek prompt templates
│   ├── library.py             # Sinologist/wuxia scholar persona
│   └── reader.py              # Wuxia literary critic persona + rating_tier validation
│
├── schema/                    # Database schema management
│   └── migrations.py          # All ALTER TABLE migrations, run idempotently
│
├── utils/                     # Product-internal utilities
│   ├── db.py                  # connect_catalog() -- thin DuckDB wrapper
│   └── llm_client.py          # DeepSeek client (LLMRequest/LLMResponse)
│
├── config/
│   └── defaults.py            # Default paths, batch sizes, worker counts
│
├── cli/
│   └── enrich.py              # Unified CLI: library / reader / csv / status
│
└── tests/
```

## Commands

```bash
cd azure_register

# Library enrichment (factual metadata via DeepSeek)
python -m cli.enrich library --dry-run
python -m cli.enrich library --limit 5 --diff
python -m cli.enrich library --author "Jin Yong" --unenriched-only
python -m cli.enrich library --sync-status   # Also update status.json files

# Reader enrichment (subjective metadata via DeepSeek)
python -m cli.enrich reader --dry-run
python -m cli.enrich reader --limit 10 --diff
python -m cli.enrich reader --unenriched-only

# CSV import
python -m cli.enrich csv --csv /path/to/works.csv

# Enrichment status
python -m cli.enrich status
```

Shared CLI args: `--db`, `--dry-run`, `--diff`, `--limit`, `--author`, `--unenriched-only`, `--batch-size`, `--workers`

## Database Schema

### works table (enriched columns)

| Column | Source | Description |
|--------|--------|-------------|
| `publication_year` | library | Year of first serialization |
| `publication_note` | library | Publication context |
| `setting_period` | library | Historical setting |
| `summary` | library/csv | 1-2 sentence synopsis |
| `category_english` | library/csv | Genre tags |
| `enriched_at` | library | Timestamp of library enrichment |
| `rating_tier` | reader | masterpiece/acclaimed/solid/minor/obscure/controversial |
| `rating_note` | reader | Critical context for rating |
| `writing_style` | reader | Style descriptors |
| `themes` | reader | Thematic tags |
| `mood` | reader | Tone/atmosphere |
| `comparable_works` | reader | Reader recommendation |
| `wuxia_era` | reader | Genre evolution placement |
| `reader_enriched_at` | reader | Timestamp of reader enrichment |

### authors table (enriched columns)

| Column | Source | Description |
|--------|--------|-------------|
| `pen_name_origin` | library | Etymology of pen name |
| `writing_style` | reader | Signature literary style |
| `best_known_for` | reader | Notable works and contributions |

## Enrichment Modes

### Library (factual)
- **Persona**: Sinologist/wuxia scholar
- **Temperature**: 0.2 (factual precision)
- **Batch size**: 15 works per API call
- **Fields**: publication_year, publication_note, setting_period, summary, category_english
- **Author fields**: birth_year, death_year, pen_name_origin, wikipedia_url
- **Behavior**: Only fills empty fields (never overwrites); suggests title_english changes as `_suggestion`

### Reader (subjective)
- **Persona**: Wuxia literary critic
- **Temperature**: 0.3
- **Batch size**: 10 works per API call
- **Fields**: rating_tier, rating_note, writing_style, themes, mood, comparable_works, wuxia_era
- **Author fields**: writing_style, best_known_for
- **Validation**: rating_tier fuzzy-matched to 6 fixed values

### CSV (import)
- **No LLM**: Purely CSV-to-DB import
- **Fields**: title_english, author_english, category_english, summary, work_link
- **Matching**: By directory_number (handles `work_NNNN` and `wuxia_NNNN` key formats)

## Design Decisions

- **No cross-imports**: Does not import from iron_abacus, jade_shuttle, or crimson_folio
- **Own DB client**: `utils/db.py` connects to DuckDB directly
- **Own LLM client**: `utils/llm_client.py` for DeepSeek only
- **Shared DuckDB**: Reads/writes `works_translator.duckdb` (same DB as other products)
- **Idempotent migrations**: All schema changes in `schema/migrations.py`, safe to re-run
- **Fill-only**: Never overwrites existing non-null values

## Environment

API keys loaded from `.env` (checked in order):
1. `azure_register/.env`
2. Workspace root `.env`
3. `iron_abacus_translator/.env`

Required: `DEEPSEEK_API_KEY` (for library and reader enrichment)
