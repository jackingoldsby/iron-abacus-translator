# Agent: epub-builder

EPUB builder agent scoped to the **Crimson Folio** (丹帙) product.

## Scope

This agent works exclusively within `crimson_folio/`:
- `builders/` — Core EPUB3 assembly (epub_builder.py, cover_page.py, chapter_renderer.py, glossary_renderer.py)
- `covers/` — Cover image pipeline (researcher.py, searcher.py, downloader.py, composer.py)
- `styles/` — CSS themes (kindle.css, modern.css, minimal.css)
- `delivery/` — Kindle email delivery (kindle_sender.py, send_to_kindle.py)
- `utils/` — LLM client, catalog lookup
- `cli/` — CLI entry points
- `config/` — Default paths and settings
- `tests/` — EPUB output tests

## Key Patterns

### EPUB3 Builder
The main builder (`builders/epub_builder.py`) produces Kindle-ready EPUB3 with:
- Popup footnotes via `epub:type="noteref"` / `epub:type="footnote"`
- Content-type-aware formatting (narrative, dialogue, verse, document, thought)
- Dialogue segmentation with quote/attribution detection
- Bilingual title pages and chapter headings
- Per-chapter footnote renumbering at build time

### Cover Image Pipeline
Covers must use **genuine period artwork** — actual historical paintings, scrolls, and prints from the dynasty depicted in the novel. No modern illustrations or AI-generated images.

Pipeline: DeepSeek research → Wikimedia/Met Museum search → download/validate → Pillow composition

### Theme System
CSS themes in `styles/`. Default is `kindle.css` (optimized for Kindle Paperwhite/Oasis). Future themes: modern, minimal.

## Product Boundaries

Crimson Folio does NOT:
- Import from `iron_abacus_translator/` or `jade_shuttle/`
- Perform translation or footnote cleanup
- Generate glossary data (it only renders entries passed to it)

It DOES:
- Read from the shared DuckDB catalog (`utils/catalog.py`)
- Use DeepSeek for cover image research (`utils/llm_client.py`)
- Renumber footnotes per-chapter at EPUB build time

## Data Flow

```
iron_abacus stage 7 JSON → crimson_folio → EPUB 3.0 → Kindle (optional)
                                ↕
                    DuckDB catalog (series metadata)
                    DeepSeek (cover art research)
                    Wikimedia/Met Museum (public domain art)
```
