"""Extractor registry — maps file extensions to extractors."""

from pathlib import Path
from typing import Dict, Optional

from extractors.base import BaseExtractor
from extractors.epub_extractor import EpubExtractor

# Registry of all available extractors
_EXTRACTORS: Dict[str, BaseExtractor] = {}


def _register_defaults():
    """Register built-in extractors."""
    epub_ext = EpubExtractor()
    for ext in epub_ext.supported_extensions():
        _EXTRACTORS[ext] = epub_ext


def get_extractor(file_path: Path) -> Optional[BaseExtractor]:
    """Get the appropriate extractor for a file based on its extension."""
    if not _EXTRACTORS:
        _register_defaults()
    return _EXTRACTORS.get(file_path.suffix.lower())


def register_extractor(extractor: BaseExtractor):
    """Register a custom extractor."""
    if not _EXTRACTORS:
        _register_defaults()
    for ext in extractor.supported_extensions():
        _EXTRACTORS[ext] = extractor
