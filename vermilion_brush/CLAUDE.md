# CLAUDE.md — Vermilion Brush (朱筆)

Scanned PDF OCR product. Extracts text from scanned Chinese PDFs and emits **Jade Shuttle-compatible raw JSON** for downstream translation by Iron Abacus.

## Architecture

```
extractors/     →  ocr/           →  structurers/
(PDF → images)     (PaddleOCR)       (classify, detect hui, emit JSON)
```

1. **Extractors** render PDF pages to images (PyMuPDF) and preprocess (binarize, deskew, crop margins).
2. **OCR** runs PaddleOCR with vertical text detection, then reorders columns right-to-left into reading order.
3. **Structurers** classify pages (cover/preface/body/blank), detect 回 boundaries, and emit the raw JSON contract.

## CLI Commands

```bash
cd vermilion_brush

# Preview a few pages
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

## Raw JSON Contract

Output matches the Jade Shuttle contract with two extra provenance fields per content block:

```json
{
  "metadata": {"title": "三俠五義", "creator": "石玉昆", "language": "zh-Hant", ...},
  "source": "NTUL-9910002853F01_三俠五義_v.1.pdf",
  "number_of_characters": 500000,
  "toc": [{"full_title": "第一回 ...", "chapter_ref": "chapter_0"}],
  "chapters": [{
    "title": "第一回 ...",
    "content": [
      {"tag": "p", "content": "...", "source_pdf": "filename.pdf", "source_pages": "30-31"}
    ]
  }]
}
```

`source_pdf` and `source_pages` enable sanity-checking OCR against the original scans.

## OCR Engine

- **PaddleOCR** with `use_angle_cls=True` for vertical text detection
- Vertical columns reordered right-to-left (classical Chinese reading order)
- Post-processing fixes common OCR confusions and normalizes punctuation

## Key Design Principles

- **No LLMs** — OCR is purely local (PaddleOCR models)
- **No imports from other products** — communicates via JSON files only
- **Provenance tracking** — every content block traces back to source PDF + page number
