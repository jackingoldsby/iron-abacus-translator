# CLAUDE.md — Ivory Helm (象牙舵)

Iterative OCR orchestrator. Drives the feedback loop across Silver Gauge (slice), Bronze Mirror (OCR), and Platinum Scale (validate) to maximize per-page OCR quality.

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │              Ivory Helm                  │
                    │         (iteration controller)           │
                    └──────┬──────────┬──────────┬────────────┘
                           │          │          │
                    ┌──────▼──┐ ┌─────▼────┐ ┌──▼──────────┐
                    │ Silver  │ │ Bronze   │ │ Platinum    │
                    │ Gauge   │ │ Mirror   │ │ Scale       │
                    │ (slice) │ │ (OCR)    │ │ (validate)  │
                    └─────────┘ └──────────┘ └─────────────┘
```

Per-page loop:
1. **Slice** — Silver Gauge detects columns, slices strips
2. **OCR** — Bronze Mirror Phase 1 OCRs each strip
3. **Validate** — Platinum Scale classifies each strip's OCR text via nano
4. **Assess** — Ivory Helm checks quality thresholds
5. If fail → **re-slice** with different parameters (up to 3 strategies), go to step 2
6. If pass or max iterations → accept result, write `iteration_report.json`

## Quality Thresholds

| Metric | Threshold | Meaning |
|--------|-----------|---------|
| `kept_ratio` | >= 0.5 | At least 50% of strips kept as text |
| `total_chars` | >= 30 | Merged page has meaningful content |
| `empty_strips` | <= 2 | No more than 2 strips with 0 OCR boxes |

## Re-Slice Strategies

When a page fails, Ivory Helm retries with different detection parameters:

| Iteration | smooth_k | threshold_pct | Intent |
|-----------|----------|---------------|--------|
| 1 (default) | 15 | 0.15 | Standard (from Silver Gauge adaptive) |
| 2 | 11 | 0.12 | Tighter smoothing, lower threshold |
| 3 | 19 | 0.10 | Wider smoothing, most permissive |
| 4 | 9 | 0.20 | Sharpest detection, highest threshold |

## CLI Commands

```bash
cd /path/to/workspace

# Run iterative pipeline
python -m ivory_helm.cli.run run --strips-dir /path/to/strips/ --images-dir /path/to/page_images/

# Resume (skip pages that already passed)
python -m ivory_helm.cli.run run --strips-dir /path/to/strips/ --images-dir /path/to/images/ --resume

# Show iteration results
python -m ivory_helm.cli.run report --strips-dir /path/to/strips/
```

## Output

`iteration_report.json` per page:
```json
{
  "page_label": "page_0097",
  "page_num": 97,
  "final_status": "pass",
  "iterations": [
    {
      "iteration": 1,
      "ocr_strips": 2,
      "ocr_empty": 2,
      "assessment": {"pass": false, "reason": "empty_strips=2 > 2; chars=0 < 30"}
    },
    {
      "iteration": 2,
      "reslice_strategy": {"smooth_k": 11, "threshold_pct": 0.12},
      "strip_count": 11,
      "ocr_strips": 11,
      "kept": 10,
      "assessment": {"pass": true, "reason": "ok"}
    }
  ]
}
```

## Key Design Decisions

- **No cross-product imports at module level** — Ivory Helm imports Silver Gauge, Bronze Mirror, and Platinum Scale at function call time, not at import time. This keeps the products independent.
- **File-based communication** — all state is in JSON files on disk. Each product reads/writes its own files. Ivory Helm coordinates by calling functions and checking file outputs.
- **Resume-safe** — pages with `iteration_report.json` showing "pass" are skipped on resume.
- **Source images required for re-slicing** — if `--images-dir` is not provided, Ivory Helm runs single-pass only (no re-slicing on failure).
