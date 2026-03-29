"""Per-book configuration system.

Each book gets a YAML file in ivory_helm/config/books/ that overrides defaults.
All four products (Silver Gauge, Bronze Mirror, Platinum Scale, Ivory Helm)
read from the same config so parameters stay in sync.

Config resolution:
  1. Load default.yaml (base defaults for all books)
  2. Overlay book-specific YAML if it exists (e.g. 三俠五義.yaml)
  3. CLI flags override both

Usage:
    from ivory_helm.config.book_config import load_config
    cfg = load_config("三俠五義")
    cfg.silver_gauge.smooth_k  # 15
    cfg.bronze_mirror.header_patterns  # [r"三[侠俠]...", ...]
"""

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent / "books"
DEFAULT_CONFIG = CONFIG_DIR / "default.yaml"


@dataclass
class SilverGaugeConfig:
    """Column detection and strip slicing parameters."""
    dpi: int = 150
    margin_crop_pct: float = 0.02
    smooth_k: int = 15
    threshold_pct: float = 0.15
    min_column_width: int = 30
    max_column_width: int = 120
    strip_pad: int = 15
    header_ink_pct: float = 0.02
    # Adaptive detection: expected column range for body pages
    expected_columns_min: int = 8
    expected_columns_max: int = 15


@dataclass
class BronzeMirrorConfig:
    """OCR and post-processing parameters."""
    ocr_lang: str = "ch"
    min_confidence: float = 0.6
    running_header_max_chars: int = 20
    min_body_chars: int = 20
    # Header patterns (regexes) — book-specific
    header_patterns: list[str] = field(default_factory=lambda: [
        r"^[\d一二三四五六七八九十百○]+$",  # page numbers
    ])
    # OCR shape confusion fixes — book-specific
    ocr_fixes: dict[str, str] = field(default_factory=lambda: {
        "囘": "回",
    })
    # Punctuation normalization
    normalize_punctuation: bool = True
    # OpenCC simplified→traditional
    s2t_conversion: bool = True


@dataclass
class PlatinumScaleConfig:
    """Validation parameters."""
    model: str = "gpt-4.1-nano"
    max_tokens: int = 120
    temperature: float = 0.0
    max_workers: int = 50


@dataclass
class IvoryHelmConfig:
    """Orchestration and iteration parameters."""
    max_iterations: int = 3
    min_kept_ratio: float = 0.5
    min_chars_per_page: int = 30
    max_empty_strips: int = 2
    reslice_strategies: list[dict] = field(default_factory=lambda: [
        {"smooth_k": 11, "threshold_pct": 0.12},
        {"smooth_k": 19, "threshold_pct": 0.10},
        {"smooth_k": 9,  "threshold_pct": 0.20},
    ])


@dataclass
class MetadataConfig:
    """Book metadata for JSON emission."""
    title: str = ""
    creator: str = ""
    language: str = "zh-Hant"
    source: str = ""
    publisher: str = ""


@dataclass
class BookConfig:
    """Complete configuration for processing one book."""
    book_id: str = ""
    silver_gauge: SilverGaugeConfig = field(default_factory=SilverGaugeConfig)
    bronze_mirror: BronzeMirrorConfig = field(default_factory=BronzeMirrorConfig)
    platinum_scale: PlatinumScaleConfig = field(default_factory=PlatinumScaleConfig)
    ivory_helm: IvoryHelmConfig = field(default_factory=IvoryHelmConfig)
    metadata: MetadataConfig = field(default_factory=MetadataConfig)


def _merge_dict(base: dict, overlay: dict) -> dict:
    """Deep merge overlay into base. overlay wins on conflicts."""
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _dict_to_config(data: dict) -> BookConfig:
    """Convert a flat/nested dict into a BookConfig."""
    cfg = BookConfig()
    cfg.book_id = data.get("book_id", "")

    sg = data.get("silver_gauge", {})
    for k, v in sg.items():
        if hasattr(cfg.silver_gauge, k):
            setattr(cfg.silver_gauge, k, v)

    bm = data.get("bronze_mirror", {})
    for k, v in bm.items():
        if hasattr(cfg.bronze_mirror, k):
            setattr(cfg.bronze_mirror, k, v)

    ps = data.get("platinum_scale", {})
    for k, v in ps.items():
        if hasattr(cfg.platinum_scale, k):
            setattr(cfg.platinum_scale, k, v)

    ih = data.get("ivory_helm", {})
    for k, v in ih.items():
        if hasattr(cfg.ivory_helm, k):
            setattr(cfg.ivory_helm, k, v)

    md = data.get("metadata", {})
    for k, v in md.items():
        if hasattr(cfg.metadata, k):
            setattr(cfg.metadata, k, v)

    return cfg


def load_config(book_id: str | None = None) -> BookConfig:
    """Load configuration for a book.

    Args:
        book_id: Book identifier. Looks for config/books/{book_id}.yaml.
                 If None or not found, returns defaults.

    Returns:
        BookConfig with merged defaults + book-specific overrides.
    """
    # Load defaults
    base_data = {}
    if DEFAULT_CONFIG.exists():
        with open(DEFAULT_CONFIG, "r", encoding="utf-8") as f:
            base_data = yaml.safe_load(f) or {}

    # Load book-specific overrides
    if book_id:
        book_file = CONFIG_DIR / f"{book_id}.yaml"
        if book_file.exists():
            with open(book_file, "r", encoding="utf-8") as f:
                book_data = yaml.safe_load(f) or {}
            base_data = _merge_dict(base_data, book_data)

        base_data["book_id"] = book_id

    return _dict_to_config(base_data)


def list_book_configs() -> list[str]:
    """List available book configuration files (minus .yaml extension)."""
    if not CONFIG_DIR.exists():
        return []
    return sorted(
        p.stem for p in CONFIG_DIR.glob("*.yaml")
        if p.name != "default.yaml"
    )
