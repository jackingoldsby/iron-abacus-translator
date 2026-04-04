# Product Overview

This workspace contains eleven independent products that together form a pipeline for digitizing, extracting, enriching, translating, and publishing classical Chinese literature as English-language EPUBs with scholarly annotations.

## Pipeline at a Glance

```
Source Material ──→ Extraction ──→ Raw JSON ──→ Translation ──→ EPUB
```

Scanned PDFs, EPUB ebooks, and web sources all converge on a common raw JSON format, which is then translated and assembled into final EPUB files. A shared DuckDB catalog tracks every work across the pipeline.

## Products

### Iron Abacus (鐵算盤) — `iron_abacus_translator/`

The translation engine. Takes raw JSON (from any extraction product) and produces English translations with cultural footnotes, using OpenAI and DeepSeek LLMs. Features a DAG-based pipeline with stages for cleaning, structuring, translation, footnote cleanup, and validation. Supports 32 author- and genre-specific translation prompts covering wuxia, shenmo, gong'an, historical-military, social satire, and Republican-era fiction.

### Jade Shuttle (玉梭) — `jade_shuttle/`

EPUB extraction. Parses multi-book EPUB collections into structured raw JSON. Handles five TOC strategies (hierarchical, section-per-book, flat chapters, flat single-doc, flat interleaved) to support the wide variety of Chinese ebook packaging conventions. Purely deterministic — no LLMs.

### Crimson Folio (丹帙) — `crimson_folio/`

EPUB generation. Assembles translated JSON into publication-ready EPUB3 files with CSS themes (Kindle, modern, minimal), cover art, and glossaries. Supports period artwork covers from Amber Inkstone portfolios, and direct Kindle delivery via email.

### Cobalt Loom (鈷織機) — `cobalt_loom/`

Web scraper for classical Chinese texts. Fetches full text from Wikisource (MediaWiki API) and ctext.org (HTML scraping with Nimble SDK for anti-bot bypass). Emits raw JSON in the same format as Jade Shuttle. Purely deterministic — no LLMs.

### Silver Gauge (銀規) — `silver_gauge/`

Column detection and strip slicing for scanned PDFs. Uses computer vision to detect vertical text columns in page images, validates column boundaries, and slices pages into individual strip images for OCR. Purely deterministic — no LLMs.

### Bronze Mirror (銅鏡) — `bronze_mirror/`

Strip OCR. Reads the strip images produced by Silver Gauge using local PaddleOCR models. Handles vertical Traditional Chinese text, classifies pages, detects chapter (hui) boundaries, and emits raw JSON. Purely deterministic — no LLMs.

### Platinum Scale (鉑秤) — `platinum_scale/`

Strip validation via OpenAI gpt-4.1-nano vision. Classifies each strip image as text, illustration, margin, or blank — providing a second opinion on Silver Gauge's column detection. Disagreements between Silver Gauge and Platinum Scale flag strips for re-slicing.

### Ivory Helm (象牙舵) — `ivory_helm/`

Iterative OCR orchestrator. Runs the slice-OCR-validate loop: Silver Gauge slices, Bronze Mirror OCRs, Platinum Scale validates, and if quality is insufficient, Ivory Helm re-slices with adjusted parameters and tries again. Designed to run autonomously on a Raspberry Pi.

### Azure Register (蒼籍) — `azure_register/`

Catalog enrichment. Uses DeepSeek to add factual metadata (publication year, dynasty setting, chapter count) and reader-oriented metadata (themes, mood, comparable works, rating tier) to the DuckDB work catalog.

### Amber Inkstone (琥珀硯) — `amber_inkstone/`

Period artwork curation. Researches historically appropriate artwork for each dynasty period via DeepSeek, then searches Wikimedia Commons and the Met Museum API to build image portfolios. Cover images are assigned to works and used by Crimson Folio.

### Vermilion Brush (朱筆) — `vermilion_brush/` *(legacy)*

The original scanned PDF OCR product. Replaced by the Ivory Helm orchestration of Silver Gauge + Bronze Mirror + Platinum Scale, which provides better accuracy through iterative refinement.

## Data Flow

```
Scanned PDFs  ──→  Ivory Helm [ Silver Gauge → Bronze Mirror → Platinum Scale ⟳ ]  ──→  Raw JSON ─┐
EPUB files    ──→  Jade Shuttle                                                      ──→  Raw JSON ─┤
Web sources   ──→  Cobalt Loom                                                       ──→  Raw JSON ─┤
                                                                                                    │
                   Azure Register ──→ DuckDB catalog (enrichment)                                   │
                   Amber Inkstone ──→ artwork portfolios                                            │
                                                                                                    ▼
                                                                                           Iron Abacus
                                                                                         (translation)
                                                                                                    │
                                                                                                    ▼
                                                                                          Crimson Folio
                                                                                        (EPUB generation)
                                                                                                    │
                                                                                                    ▼
                                                                                             EPUB file
```

## Shared State

All products communicate through two mechanisms:

1. **Raw JSON files** — the common interchange format between extraction and translation
2. **DuckDB databases** (local files, not remote):
   - `works_translator.duckdb` — work catalog (titles, authors, series, enrichment)
   - `pipeline_progress.duckdb` — per-stage translation progress tracking
   - `glossary.duckdb` — translation glossary
   - `artwork_portfolio.duckdb` — curated period artwork and assignments

No product imports code from another.

## LLM Usage

| Product | LLM Provider | Purpose |
|---|---|---|
| Iron Abacus | OpenAI, DeepSeek | Translation with cultural footnotes |
| Crimson Folio | DeepSeek | Cover art composition prompts |
| Azure Register | DeepSeek | Catalog metadata enrichment |
| Amber Inkstone | DeepSeek | Dynasty art research |
| Platinum Scale | OpenAI gpt-4.1-nano | Vision-based strip validation |
| Jade Shuttle | None | Deterministic extraction |
| Cobalt Loom | None | Deterministic scraping |
| Silver Gauge | None | Deterministic CV |
| Bronze Mirror | None | Local PaddleOCR only |
| Ivory Helm | None (delegates to Platinum Scale) | Orchestration only |
| Vermilion Brush | None | Legacy, local PaddleOCR only |
