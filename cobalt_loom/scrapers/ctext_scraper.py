"""ctext.org scraper — fallback for works not available on Wikisource."""

import logging
import re
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup

from cache.disk_cache import DiskCache
from config.defaults import CTEXT_BASE_URL, CTEXT_RATE_LIMIT, USER_AGENT
from scrapers.base import BaseScraper, RateLimiter
from models.core import ScrapedChapter

logger = logging.getLogger(__name__)


class CtextScraper(BaseScraper):
    """Scraper for ctext.org — HTML scraping with Nimble fallback.

    Uses Nimble Web API when available (better anti-bot handling),
    falls back to direct httpx requests otherwise.
    """

    def __init__(self, cache: Optional[DiskCache] = None, use_cache: bool = True,
                 use_nimble: bool = True):
        self.rate_limiter = RateLimiter(CTEXT_RATE_LIMIT)
        self.cache = cache if use_cache else None
        self.use_nimble = use_nimble
        self.client = httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            },
            timeout=30.0,
            follow_redirects=True,
        )

    def close(self):
        self.client.close()

    def _fetch_html(self, url: str) -> str:
        """Fetch HTML with rate limiting, caching, and optional Nimble fallback."""
        if self.cache:
            cached = self.cache.get(url)
            if cached:
                return cached

        # Try Nimble first if enabled (stealth mode for ctext.org anti-bot)
        if self.use_nimble:
            from scrapers.nimble_fetcher import nimble_extract
            html = nimble_extract(url, stealth=True)
            if html:
                if self.cache:
                    self.cache.put(url, html)
                return html

        # Direct request fallback
        self.rate_limiter.wait()
        resp = self.client.get(url)
        resp.raise_for_status()
        html = resp.text

        if self.cache:
            self.cache.put(url, html)

        return html

    def discover_chapters(self, work_path: str) -> List[str]:
        """Discover chapter URLs from a ctext.org work page.

        work_path is the ctext identifier, e.g., "baigongan".
        Returns list of chapter URLs.
        """
        url = f"{CTEXT_BASE_URL}/{work_path}/zhs"
        html = self._fetch_html(url)
        soup = BeautifulSoup(html, "lxml")

        chapters = []
        # ctext.org lists chapters as links in the table of contents
        for link in soup.select("a[href]"):
            href = link.get("href", "")
            # Chapter links typically look like /baigongan/di-yi-ze/zhs
            if href.startswith(f"/{work_path}/") and href != f"/{work_path}/zhs":
                full_url = f"{CTEXT_BASE_URL}{href}"
                if full_url not in chapters:
                    chapters.append(full_url)

        logger.info(f"Discovered {len(chapters)} chapters from ctext.org/{work_path}")
        return chapters

    def scrape_chapter(self, chapter_url: str) -> Optional[ScrapedChapter]:
        """Scrape a single chapter from ctext.org."""
        try:
            html = self._fetch_html(chapter_url)
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error scraping {chapter_url}: {e}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Request error scraping {chapter_url}: {e}")
            return None

        soup = BeautifulSoup(html, "lxml")

        # Extract title
        title_el = soup.find("h2") or soup.find("title")
        title = title_el.get_text(strip=True) if title_el else ""
        # Clean up title — remove site name suffix
        title = re.sub(r"\s*[-–—]\s*中國哲學書電子化計劃.*$", "", title)

        # Extract content from the main text div
        content_div = soup.find("div", id="content3") or soup.find("div", class_="ctext")
        if not content_div:
            logger.warning(f"No content div found for {chapter_url}")
            return None

        blocks = []
        for el in content_div.find_all(["p", "h1", "h2", "h3", "h4", "td"]):
            text = el.get_text(strip=True)
            if not text:
                continue
            tag = el.name if el.name in ("p", "h1", "h2", "h3", "h4") else "p"
            blocks.append({"tag": tag, "content": text})

        if not blocks:
            logger.warning(f"No content blocks for {chapter_url}")
            return None

        chapter = ScrapedChapter(
            title=title,
            content=blocks,
            source_url=chapter_url,
        )
        chapter.compute_character_count()
        return chapter

    def get_work_url(self, work_path: str) -> str:
        return f"{CTEXT_BASE_URL}/{work_path}/zhs"
