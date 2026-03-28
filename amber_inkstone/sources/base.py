#!/usr/bin/env python3
"""
Base class for artwork search sources.
"""

from abc import ABC, abstractmethod
from typing import List

from models.portfolio import ArtworkCandidate


class BaseSource(ABC):
    """Abstract base class for period artwork search sources."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Identifier for this source (e.g. 'wikimedia_commons')."""

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> List[ArtworkCandidate]:
        """Search for artwork matching query.

        Args:
            query: Search query string
            limit: Maximum results to return

        Returns:
            List of ArtworkCandidate objects
        """
