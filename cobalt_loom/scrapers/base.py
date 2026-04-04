"""Base scraper ABC and rate limiter."""

import time
import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from models.core import ScrapedChapter

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple rate limiter that enforces minimum delay between calls."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last_call = 0.0

    def wait(self):
        now = time.time()
        elapsed = now - self._last_call
        if elapsed < self.min_interval:
            delay = self.min_interval - elapsed
            logger.debug(f"Rate limit: sleeping {delay:.1f}s")
            time.sleep(delay)
        self._last_call = time.time()


class BaseScraper(ABC):
    """Abstract base class for web scrapers."""

    @abstractmethod
    def discover_chapters(self, page_title: str) -> List[str]:
        """Discover chapter page titles/URLs for a work.

        Returns list of chapter identifiers (page titles or URLs).
        """

    @abstractmethod
    def scrape_chapter(self, chapter_id: str) -> Optional[ScrapedChapter]:
        """Scrape a single chapter and return structured content.

        Returns None if the chapter couldn't be scraped.
        """

    @abstractmethod
    def get_work_url(self, page_title: str) -> str:
        """Return the full URL for a work's main page."""
