# CLAUDE.md — Jade Shuttle (玉梭)

Ebook extraction pipeline. Transforms multi-book ebook collections into structured JSON files for downstream translation by Iron Abacus.

## Architecture

```
extractors/     →  detectors/     →  transformers/  →  catalog/
(parse format)     (find works)       (emit JSON)       (dedup & register)
```

1. **Extractors** parse format-specific files (EPUB, future: PDF, TXT). Each extractor implements `BaseExtractor`.
2. **Detectors** identify work boundaries, chapters, and volumes within parsed content.
3. **Transformers** convert HTML to blocks, handle encoding (S2T/T2S), and emit the raw JSON contract.
4. **Catalog** deduplicates against the DuckDB catalog and registers new works.

## CLI Commands

```bash
cd jade_shuttle

# Dry run — detect and report, no files written
python -m cli.ingest --dry-run

# Process a single EPUB
python -m cli.ingest --single "萧逸*.epub" --dry-run

# Full ingestion with report
python -m cli.ingest --report /tmp/ingest_report.json

# Custom paths
python -m cli.ingest --epub-dir /path/to/epubs --output-dir /path/to/output --db-path /path/to/db.duckdb
```

## Raw JSON Contract

This is **the contract boundary** between jade_shuttle and iron_abacus_translator. The output of `transformers/json_emitter.py` must match what `iron_abacus_translator/processors/json_cleaner.py` expects:

```json
{
  "metadata": {
    "title": "繁體中文書名",
    "creator": "繁體作者名",
    "language": "zh-Hant",
    "source": "Anna's Archive",
    "publisher": null
  },
  "source": "A001.epub",
  "number_of_characters": 150000,
  "toc": [
    {"full_title": "第一回 chapter title", "chapter_ref": "chapter_0"}
  ],
  "chapters": [
    {
      "title": "第一回 chapter title",
      "content": [
        {"tag": "p", "content": "paragraph text..."},
        {"tag": "h3", "content": "heading text..."}
      ]
    }
  ]
}
```

**Never change this format without coordinating with iron_abacus_translator.**

## TOC Detection Strategies

The pipeline handles 4 EPUB TOC structures:

| Strategy | Example Authors | Structure |
|---|---|---|
| `hierarchical_works` | Huang Yi, Guzhengxia | Section(work) > Section(volume) > Leaf(chapter) |
| `section_per_book` | Liang Yusheng, Wolong Sheng | Section(book) > Leaf(chapter) |
| `flat_single_doc` | Xiao Yi, Wen Ruian | Each leaf = entire book in one HTML file |
| `flat_interleaved` | Sima Ling, Liu Canyang | Book titles + chapters mixed flat |

Detection logic is in `detectors/toc_detector.py`. Strategy dispatch is in `extractors/epub_extractor.py`.

## Adding a New Extractor

1. Create `extractors/my_format_extractor.py`
2. Implement `BaseExtractor` (see `extractors/base.py`):
   - `supported_extensions()` → `[".pdf"]`
   - `extract_works(source_path, author_hint)` → `List[DetectedWork]`
3. Register in `extractors/registry.py`
4. The extractor must populate `DetectedWork.chapters` with `Chapter` objects containing tag/content blocks

## Adding a New Detector Strategy

1. Add detection logic to `detectors/toc_detector.py`
2. Add extraction function to `detectors/work_detector.py`
3. Add to `STRATEGY_MAP` in `extractors/epub_extractor.py`

## Shared Resources

- **DuckDB catalog**: `/Users/jacki/project_files/translation_project/db/works_translator.duckdb`
- **Output directory**: `/Users/jacki/project_files/translation_project/wuxia_individual_files/`
- **EPUB source**: `/Users/jacki/project_files/translation_project/for_parsing/`

## Key Design Principles

- **No LLMs** — purely deterministic parsing and pattern matching
- **No imports from iron_abacus_translator** — the two products communicate only through JSON files and the shared DuckDB catalog
- **Volume grouping** — multi-volume works are detected by `strip_volume_marker()` and grouped into `WorkGroup` objects
- **Deduplication** — titles are normalized and matched against the existing catalog before registration
