# CLAUDE.md — Silver Gauge (銀規)

Column detection and strip slicing product. Detects vertical text columns in scanned page images, validates them against degenerate detection, slices into ordered/tagged strip images, and saves persistently with metadata.

## Architecture

```
extractors/     →  detectors/
(PDF → images)     (detect columns, validate, slice, classify)
```

1. **Extractors** render PDF pages to images (PyMuPDF) and preprocess (crop margins only — PaddleOCR performs best on raw images).
2. **Detectors** find vertical text columns via projection profile, validate widths (reject degenerate detections), slice into strip images, and classify strips by ink density.

## No LLMs, No OCR

Silver Gauge is purely deterministic computer vision. It detects and slices columns but does **not** perform OCR. OCR is handled downstream by Bronze Mirror.

## CLI Commands

```bash
cd /path/to/workspace

# Slice a single PDF (all pages)
python -m silver_gauge.cli.slice --pdf /path/to/vol1.pdf --output-dir /path/to/strips/

# Slice specific page range
python -m silver_gauge.cli.slice --pdf /path/to/vol1.pdf --pages 80-97 --output-dir /path/to/strips/

# Slice all PDFs in a directory
python -m silver_gauge.cli.slice --dir /path/to/三俠五義_俞平伯校點本/ --output-dir /path/to/strips/

# Dry run — show detection stats, no writes
python -m silver_gauge.cli.slice --pdf /path/to/vol1.pdf --dry-run
```

## Output Structure

```
ocr_strips/{work_id}/
├── manifest.json              # source PDFs, page count, detection params
├── vol1/
│   ├── page_0080/
│   │   ├── detection.json     # column metadata + strip classification
│   │   ├── strip_000.png      # rightmost column (RTL reading order)
│   │   ├── strip_001.png
│   │   └── ...
│   └── ...
└── vol2/
    └── ...
```

## Key Design Decisions

- **Degenerate detection guard**: Columns wider than `MAX_COLUMN_WIDTH` (120px at 150 DPI) are rejected. This handles pages where detection produces 2 huge "columns" spanning the whole page.
- **Strip classification**: Strips with <2% ink density are classified as `header_only` and skipped by downstream OCR.
- **Persistent strips**: All strip images are saved to disk. No ephemeral temp files. This enables debugging, resumption, and parallelization.
- **Page-by-page validation**: During slicing, each page's detection results are logged with strip counts and degenerate drop counts for immediate quality assessment.
- **No preprocessing beyond margin cropping**: Benchmarks showed binarization, sharpening, CLAHE, and deskew all hurt PaddleOCR accuracy.

## Detection Parameters

| Parameter | Default | Notes |
|-----------|---------|-------|
| DPI | 150 | Sweet spot for PaddleOCR |
| smooth_k | 15 | Moving average kernel |
| threshold_pct | 0.15 | 15% of max projection |
| min_width | 30px | Minimum column width |
| max_width | 120px | Degenerate guard |
| pad | 15px | Padding on each side |
| ink_threshold | 0.02 | Header strip detection |
