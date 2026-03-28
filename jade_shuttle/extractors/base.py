"""Base extractor interface."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from models.core import DetectedWork


class BaseExtractor(ABC):
    """Base class for all format-specific extractors."""

    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """Return list of file extensions this extractor handles (e.g., ['.epub'])."""

    @abstractmethod
    def extract_works(self, source_path: Path, author_hint: str = "") -> List[DetectedWork]:
        """Extract individual works from a source file."""
