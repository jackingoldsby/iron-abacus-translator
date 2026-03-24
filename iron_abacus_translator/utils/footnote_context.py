#!/usr/bin/env python3
"""
Cross-Block Footnote Accumulator

Thread-safe tracker for which ideograms have been footnoted across
an entire work. Enables generation-time deduplication by informing
the translator which terms have already been explained.

This is a new standalone module -- existing translator.py and wrappers
are NOT modified.

Usage:
    from utils.footnote_context import FootnoteContextAccumulator

    accumulator = FootnoteContextAccumulator()
    accumulator.register(["江湖", "內功"], chapter_num=1)
    accumulator.is_already_footnoted("江湖")  # True
"""

import json
import threading
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

logger = logging.getLogger(__name__)


class FootnoteContextAccumulator:
    """
    Thread-safe accumulator tracking which ideograms have been footnoted
    across the entire work.

    Used by the glossary context builder to suppress duplicate footnotes
    at generation time rather than cleaning them up post-hoc.
    """

    def __init__(self):
        self._seen: Dict[str, int] = {}  # ideogram -> chapter where first seen
        self._lock = threading.Lock()

    def register(self, ideograms: List[str], chapter_num: int) -> None:
        """
        Register ideograms as footnoted in a given chapter.

        Only records the first occurrence -- subsequent calls for the
        same ideogram are no-ops.

        Args:
            ideograms: List of Chinese ideograms that were footnoted
            chapter_num: Chapter number where footnotes appeared
        """
        with self._lock:
            for ideogram in ideograms:
                if ideogram not in self._seen:
                    self._seen[ideogram] = chapter_num
                    logger.debug(
                        f"Registered footnote for '{ideogram}' in chapter {chapter_num}"
                    )

    def is_already_footnoted(self, ideogram: str) -> bool:
        """
        Check if an ideogram has already been footnoted in an earlier block.

        Args:
            ideogram: Chinese ideogram to check

        Returns:
            True if this ideogram was already footnoted
        """
        with self._lock:
            return ideogram in self._seen

    def get_already_footnoted(self, ideograms: List[str]) -> List[str]:
        """
        Filter a list of ideograms to return only those already footnoted.

        Args:
            ideograms: List of ideograms to check

        Returns:
            Subset of ideograms that have already been footnoted
        """
        with self._lock:
            return [ig for ig in ideograms if ig in self._seen]

    def get_new_ideograms(self, ideograms: List[str]) -> List[str]:
        """
        Filter a list of ideograms to return only those NOT yet footnoted.

        Args:
            ideograms: List of ideograms to check

        Returns:
            Subset of ideograms that have NOT been footnoted yet
        """
        with self._lock:
            return [ig for ig in ideograms if ig not in self._seen]

    def get_first_chapter(self, ideogram: str) -> Optional[int]:
        """
        Get the chapter number where an ideogram was first footnoted.

        Args:
            ideogram: Chinese ideogram to look up

        Returns:
            Chapter number or None if not yet footnoted
        """
        with self._lock:
            return self._seen.get(ideogram)

    @property
    def total_registered(self) -> int:
        """Total number of unique ideograms registered."""
        with self._lock:
            return len(self._seen)

    @property
    def all_footnoted_ideograms(self) -> Set[str]:
        """Return a copy of all footnoted ideograms."""
        with self._lock:
            return set(self._seen.keys())

    def save(self, path: Union[str, Path]) -> None:
        """
        Persist accumulator state to a JSON file.

        Use between volumes of a multi-volume work so dedup
        carries across volume boundaries.

        Args:
            path: File path to write JSON state to
        """
        path = Path(path)
        with self._lock:
            state = {
                "version": 1,
                "seen": self._seen,
            }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        logger.info(
            f"Saved accumulator state ({len(self._seen)} ideograms) to {path}"
        )

    @classmethod
    def load(cls, path: Union[str, Path]) -> "FootnoteContextAccumulator":
        """
        Load accumulator state from a previously saved JSON file.

        Args:
            path: File path to read JSON state from

        Returns:
            New FootnoteContextAccumulator with restored state
        """
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        acc = cls()
        acc._seen = state.get("seen", {})
        # JSON keys are strings; chapter nums need to stay as ints
        acc._seen = {k: int(v) for k, v in acc._seen.items()}
        logger.info(
            f"Loaded accumulator state ({len(acc._seen)} ideograms) from {path}"
        )
        return acc

    def clear(self) -> None:
        """Reset the accumulator (e.g., for testing)."""
        with self._lock:
            self._seen.clear()

    def __repr__(self) -> str:
        with self._lock:
            return f"FootnoteContextAccumulator(registered={len(self._seen)})"
