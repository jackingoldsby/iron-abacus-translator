"""Default configuration for Platinum Scale strip validation."""

from pathlib import Path

# LLM — text-only validation (reads OCR output, no vision)
VALIDATION_MODEL = "gpt-4.1-nano"
VALIDATION_MAX_TOKENS = 120  # Tiny responses: just classification + reason
VALIDATION_TEMPERATURE = 0.0

# OCR confidence fast path — skip nano if PaddleOCR is very confident
# Strips with confidence_mean >= this threshold are auto-classified as "text"
OCR_HIGH_CONFIDENCE_THRESHOLD = 0.95

# Character count floor — strips with this many chars are body text, not headers
# Real running headers (三俠五義, 第一回, page numbers) are ≤15 chars
# Prevents nano from misclassifying long body text as headers
MIN_CHARS_FOR_BODY_TEXT = 20

# Parallelism — nano is cheap, blast through strips
MAX_WORKERS = 50

# Cost tracking
# gpt-4.1-nano: $0.10/1M input, $0.40/1M output (as of 2026-03)
# Text-only: ~200 tokens input per strip, ~40 tokens output
# 12 strips × 18 pages = 216 strips × ~240 tokens ≈ 52K tokens ≈ $0.002/chapter
COST_PER_1M_INPUT = 0.10
COST_PER_1M_OUTPUT = 0.40

# Iteration: when Platinum Scale flags problems, Silver Gauge can re-slice
# with different parameters. Max iterations before giving up.
MAX_RESLICE_ITERATIONS = 3

# Paths
DEFAULT_STRIPS_BASE = Path(
    "/Users/jacki/project_files/translation_project/work_individual_files/ocr_strips"
)
