"""Default configuration for Ivory Helm OCR orchestration."""

from pathlib import Path

# Iteration limits
MAX_ITERATIONS = 3  # Max slice→OCR→validate loops per page before accepting result

# Quality thresholds — a page passes if:
MIN_KEPT_RATIO = 0.5       # At least 50% of strips classified as text by nano
MIN_CHARS_PER_PAGE = 30    # At least 30 chars after merge (else likely blank/failed)
MAX_EMPTY_STRIPS = 2       # At most 2 strips with 0 OCR boxes before re-slicing

# Re-slice strategy: parameter perturbations to try on failing pages
RESLICE_STRATEGIES = [
    # (smooth_k, threshold_pct) — progressively looser detection
    {"smooth_k": 11, "threshold_pct": 0.12},
    {"smooth_k": 19, "threshold_pct": 0.10},
    {"smooth_k": 9,  "threshold_pct": 0.20},
]

# Paths
DEFAULT_STRIPS_BASE = Path(
    "/Users/jacki/project_files/translation_project/work_individual_files/ocr_strips"
)
DEFAULT_SOURCE_DIR = Path("/Users/jacki/project_files/translation_project/for_parsing")
