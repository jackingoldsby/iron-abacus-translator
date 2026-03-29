# CLAUDE.md — Bronze Mirror (銅鏡)

Strip OCR product. Reads pre-sliced strip images from Silver Gauge, runs PaddleOCR on each strip, postprocesses (simplified→traditional, error fixes, header stripping), merges into reading-order text, and emits Jade Shuttle-compatible raw JSON.

## Architecture

```
readers/        →  ocr/            →  structurers/
(strip reader)     (PaddleOCR)        (classify, detect hui, emit JSON)
```

1. **Readers** iterate over strip directories, read `detection.json`, OCR each strip, write per-strip results, merge into page text. Support resume (skip pages with `ocr_merged.txt`).
2. **OCR** wraps PaddleOCR (v2/v3 auto-detect), filters low-confidence boxes.
3. **Postprocessor** applies OpenCC simplified→traditional conversion, punctuation normalization, OCR shape-confusion fixes, running header stripping.
4. **Structurers** classify pages, detect 回 boundaries, emit raw JSON.

## No LLMs

Bronze Mirror uses local PaddleOCR models only. No API keys needed.

## CLI Commands

```bash
cd /path/to/workspace

# OCR a sliced book
python -m bronze_mirror.cli.read --strips-dir /path/to/ocr_strips/三俠五義/ --output /path/to/raw.json

# Resume interrupted OCR
python -m bronze_mirror.cli.read --strips-dir /path/to/ocr_strips/三俠五義/ --output /path/to/raw.json --resume

# OCR specific pages only
python -m bronze_mirror.cli.read --strips-dir /path/to/ocr_strips/三俠五義/ --pages 80-97

# Show failed strips
python -m bronze_mirror.cli.read --strips-dir /path/to/ocr_strips/三俠五義/ --show-failures
```

## Per-Strip Results

Each strip produces `ocr_strip_NNN.json`:
```json
{
  "strip_index": 7,
  "strip_file": "strip_007.png",
  "text": "",
  "box_count": 0,
  "confidence_mean": null,
  "chars": 0,
  "status": "empty"
}
```

Status values: `"ok"`, `"empty"` (0 boxes on text strip), `"skipped"` (header_only), `"missing"` (strip file not found).

## Key Design Decisions

- **Resume support**: Pages with existing `ocr_merged.txt` are skipped. Safe to interrupt and restart.
- **Persistent per-strip results**: Every strip's OCR result is saved. Failed strips (0 boxes) are flagged but the strip image persists for debugging.
- **OpenCC "ch" model**: PaddleOCR's `ch` detection model (PP-OCRv4) is far superior to `chinese_cht`. Simplified output is converted to traditional via OpenCC in post-processing.
- **Header stripping**: Running headers (三俠五義, 第N回, page numbers) are removed by regex after text merge.

## Raw JSON Contract

Output matches the Jade Shuttle contract with provenance fields:
```json
{
  "metadata": {"title": "三俠五義", "creator": "石玉昆", "language": "zh-Hant", ...},
  "source": "NTUL-9910002853F01_三俠五義_v.1.pdf",
  "number_of_characters": 500000,
  "toc": [{"full_title": "第一回 ...", "chapter_ref": "chapter_0"}],
  "chapters": [{
    "title": "第一回 ...",
    "content": [{"tag": "p", "content": "...", "source_pdf": "...", "source_pages": "30-31"}]
  }]
}
```

## Validation

```bash
# Validate chapter 1 against Wikisource ground truth
python bronze_mirror/scripts/validate_chapter1.py

# Resume (skip slicing if strips exist)
python bronze_mirror/scripts/validate_chapter1.py --resume
```
