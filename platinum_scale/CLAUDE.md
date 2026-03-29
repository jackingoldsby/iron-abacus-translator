# CLAUDE.md — Platinum Scale (鉑秤)

Strip validation product. Reads Bronze Mirror's per-strip OCR results (text + metadata) and validates each via **gpt-4.1-nano** (text-only, no vision). Catches headers, noise, and blank strips that should be excluded from the final merge.

## Architecture

```
bronze_mirror phase1 (OCR strips)  →  platinum_scale (validate OCR text)  →  bronze_mirror phase2 (merge)
```

1. **Validators** read `ocr_strip_NNN.json` files produced by Bronze Mirror Phase 1.
2. Each strip's OCR text, character count, confidence, and box count are sent to gpt-4.1-nano.
3. Nano classifies: `text`, `header`, `blank`, `noise`, `merged`.
4. Results written as `validation.json` per page.
5. Bronze Mirror Phase 2 reads `validation.json` and excludes strips nano flagged as non-text.

## Why Text-Based (Not Vision)

- Nano can't reliably read classical Chinese typography from images
- OCR text is available from Bronze Mirror Phase 1 — validate the *output* not the *input*
- **$0.002 per chapter** (text-only: ~240 tokens/strip vs ~600 for vision)
- Fast path: empty/skipped strips bypass the API entirely

## CLI Commands

```bash
cd /path/to/workspace

# Validate all strips (requires Bronze Mirror phase1 to have run first)
python -m platinum_scale.cli.validate --strips-dir /path/to/ocr_strips/三俠五義_validation/

# Resume (skip already-validated pages)
python -m platinum_scale.cli.validate --strips-dir /path/to/strips/ --resume

# Show validation report (no API calls)
python -m platinum_scale.cli.validate --strips-dir /path/to/strips/ --report

# Show disagreements between Silver Gauge heuristic and nano
python -m platinum_scale.cli.validate --strips-dir /path/to/strips/ --show-disagreements
```

## Output

`validation.json` per page:
```json
{
  "page_label": "page_0085",
  "total_strips": 11,
  "validated": 11,
  "kept": 9,
  "excluded": 2,
  "strips": [
    {
      "strip_index": 0,
      "nano_classification": "text",
      "ocr_text_preview": "那日包公正在書房...",
      "ocr_chars": 42,
      "reason": "coherent classical Chinese narrative"
    }
  ]
}
```
