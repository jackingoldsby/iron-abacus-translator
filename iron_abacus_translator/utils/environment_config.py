#!/usr/bin/env python3
"""
Environment Configuration Management

Centralizes all environment-specific paths and settings.
All paths derive from TRANSLATOR_DATA_ROOT.

Usage:
    from utils.environment_config import get_config

    config = get_config()
    print(config.source_dir)
    print(config.catalog_path)
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Default data root per platform
_DEFAULT_DATA_ROOT = Path.home() / "project_files" / "translation_project"


@dataclass
class EnvironmentConfig:
    """
    Centralized environment configuration.

    All paths derive from data_root (TRANSLATOR_DATA_ROOT env var).
    Individual paths can be overridden via their own env vars.
    """
    data_root: Path

    # Source data paths
    source_dir: Path = None
    raw_dir: Path = None
    catalog_path: Path = None
    glossary_path: Path = None

    # Output paths
    output_dir: Path = None
    wip_dir: Path = None
    epub_dir: Path = None
    log_dir: Path = None

    # Target language (ISO 639-1 code, default English)
    target_lang: str = "en"

    # Project root (code directory, auto-detected)
    project_root: Path = None

    def __post_init__(self):
        """Derive defaults from data_root for any paths not explicitly set."""
        self.data_root = Path(self.data_root)

        if self.source_dir is None:
            self.source_dir = self.data_root / "cleaned" / "COMPLETE_ALL_BOOKS"
        self.source_dir = Path(self.source_dir)

        if self.raw_dir is None:
            self.raw_dir = self.data_root / "raw"
        self.raw_dir = Path(self.raw_dir)

        if self.catalog_path is None:
            self.catalog_path = self.data_root / "db" / "works_translator.duckdb"
        self.catalog_path = Path(self.catalog_path)

        if self.glossary_path is None:
            self.glossary_path = self.data_root / "db" / "glossary.duckdb"
        self.glossary_path = Path(self.glossary_path)

        if self.output_dir is None:
            self.output_dir = self.data_root / "translated"
        self.output_dir = Path(self.output_dir)

        if self.wip_dir is None:
            self.wip_dir = self.data_root / "wip"
        self.wip_dir = Path(self.wip_dir)

        if self.epub_dir is None:
            self.epub_dir = self.data_root / "epub"
        self.epub_dir = Path(self.epub_dir)

        if self.log_dir is None:
            self.log_dir = self.data_root / "logs"
        self.log_dir = Path(self.log_dir)

        if self.project_root is None:
            self.project_root = detect_project_root()
        self.project_root = Path(self.project_root)

    def validate(self) -> list[str]:
        """Validate that required paths exist. Returns list of errors."""
        errors = []
        if not self.catalog_path.exists():
            errors.append(f"Catalog database not found: {self.catalog_path}")
        if not self.source_dir.exists():
            errors.append(f"Source directory not found: {self.source_dir}")
        return errors

    def ensure_dirs(self):
        """Create output directories if they don't exist."""
        for d in [self.output_dir, self.wip_dir, self.epub_dir, self.log_dir]:
            d.mkdir(parents=True, exist_ok=True)


def detect_project_root() -> Path:
    """Detect project root by searching upward for .git or pyproject.toml."""
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        if (parent / '.git').exists() or (parent / 'pyproject.toml').exists():
            return parent
        if (parent / 'processors').exists() and (parent / 'utils').exists():
            return parent
    return current


def get_config(
    project_root: Optional[Path] = None,
    load_dotenv: bool = True,
) -> EnvironmentConfig:
    """
    Load environment configuration.

    Priority: env vars > .env file > defaults.
    All paths derive from TRANSLATOR_DATA_ROOT unless individually overridden.
    """
    if project_root is None:
        project_root = detect_project_root()

    # Attempt to load .env file
    if load_dotenv:
        try:
            from dotenv import load_dotenv as _load_env
            env_path = project_root / '.env'
            if env_path.exists():
                _load_env(env_path)
                logger.info(f"Loaded environment from {env_path}")
        except ImportError:
            logger.debug("python-dotenv not installed, skipping .env loading")

    data_root = Path(os.getenv('TRANSLATOR_DATA_ROOT', str(_DEFAULT_DATA_ROOT)))

    def _env_path(var_name: str) -> Optional[Path]:
        val = os.getenv(var_name)
        return Path(val) if val else None

    config = EnvironmentConfig(
        data_root=data_root,
        source_dir=_env_path('TRANSLATOR_SOURCE_DIR'),
        raw_dir=_env_path('TRANSLATOR_RAW_DIR'),
        catalog_path=_env_path('TRANSLATOR_CATALOG_PATH'),
        glossary_path=_env_path('TRANSLATOR_GLOSSARY_PATH'),
        output_dir=_env_path('TRANSLATOR_OUTPUT_DIR'),
        wip_dir=_env_path('TRANSLATOR_WIP_DIR'),
        epub_dir=_env_path('TRANSLATOR_EPUB_DIR'),
        log_dir=_env_path('TRANSLATOR_LOG_DIR'),
        project_root=project_root,
    )

    logger.debug(f"Config: data_root={config.data_root}, source={config.source_dir}")
    return config


# Module-level singleton
_CONFIG: Optional[EnvironmentConfig] = None


def get_or_create_config() -> EnvironmentConfig:
    """Get or create singleton configuration."""
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = get_config()
    return _CONFIG


def reset_config():
    """Reset singleton (useful for testing)."""
    global _CONFIG
    _CONFIG = None


# Backwards-compatible aliases
get_env_config = get_config
get_or_create_env_config = get_or_create_config
reset_env_config = reset_config


if __name__ == "__main__":
    import sys
    print("=" * 60)
    print("Environment Configuration")
    print("=" * 60)

    config = get_config()
    print(f"\nData Root:    {config.data_root}")
    print(f"Source Dir:   {config.source_dir}")
    print(f"Raw Dir:      {config.raw_dir}")
    print(f"Catalog:      {config.catalog_path}")
    print(f"Glossary:     {config.glossary_path}")
    print(f"Output Dir:   {config.output_dir}")
    print(f"WIP Dir:      {config.wip_dir}")
    print(f"EPUB Dir:     {config.epub_dir}")
    print(f"Log Dir:      {config.log_dir}")
    print(f"Project Root: {config.project_root}")

    errors = config.validate()
    if errors:
        print("\nValidation errors:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("\nAll paths valid.")
