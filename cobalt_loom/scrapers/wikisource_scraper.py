"""Wikisource scraper using MediaWiki API."""

import json
import logging
import re
import threading
from typing import List, Optional
from urllib.parse import quote, urlencode

import httpx

from cache.disk_cache import DiskCache
from config.defaults import (
    WIKISOURCE_API_URL,
    WIKISOURCE_BASE_URL,
    WIKISOURCE_RATE_LIMIT,
    USER_AGENT,
)
from scrapers.base import BaseScraper, RateLimiter
from structurers.html_to_blocks import html_to_blocks
from models.core import ScrapedChapter

logger = logging.getLogger(__name__)


class WikisourceScraper(BaseScraper):
    """Scraper for zh.wikisource.org using the MediaWiki API."""

    def __init__(self, cache: Optional[DiskCache] = None, use_cache: bool = True,
                 use_nimble: bool = True):
        self.rate_limiter = RateLimiter(WIKISOURCE_RATE_LIMIT)
        self.cache = cache if use_cache else None
        self.use_nimble = use_nimble
        self._nimble_ok = None  # lazy check
        self._lock = threading.Lock()
        self._thread_local = threading.local()
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
            follow_redirects=True,
        )

    def close(self):
        self.client.close()

    def _nimble_available(self) -> bool:
        if self._nimble_ok is None:
            if self.use_nimble:
                from scrapers.nimble_fetcher import is_nimble_available
                self._nimble_ok = is_nimble_available()
            else:
                self._nimble_ok = False
        return self._nimble_ok

    def _get_thread_client(self) -> httpx.Client:
        """Get a thread-local httpx client for direct requests."""
        if not hasattr(self._thread_local, 'client'):
            self._thread_local.client = httpx.Client(
                headers={"User-Agent": USER_AGENT},
                timeout=30.0,
                follow_redirects=True,
            )
        return self._thread_local.client

    def _api_get(self, params: dict) -> dict:
        """Make a MediaWiki API request with rate limiting and caching."""
        params = {**params, "format": "json"}
        url = WIKISOURCE_API_URL

        # Build cache key from sorted params
        cache_key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))

        if self.cache:
            with self._lock:
                cached = self.cache.get(cache_key)
            if cached:
                return json.loads(cached)

        # Try Nimble first for IP rotation and scale
        if self._nimble_available():
            data = self._api_get_via_nimble(url, params)
            if data is not None:
                if self.cache:
                    with self._lock:
                        self.cache.put(cache_key, json.dumps(data, ensure_ascii=False))
                return data
            # Fall through to direct request

        self.rate_limiter.wait()
        client = self._get_thread_client()
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        if self.cache:
            with self._lock:
                self.cache.put(cache_key, json.dumps(data, ensure_ascii=False))

        return data

    def _api_get_via_nimble(self, base_url: str, params: dict) -> dict | None:
        """Fetch a MediaWiki API response through Nimble."""
        from scrapers.nimble_fetcher import nimble_fetch_raw

        full_url = base_url + "?" + urlencode(params)
        raw = nimble_fetch_raw(full_url)
        if not raw:
            return None

        # Nimble returns the content as HTML wrapper — extract JSON
        # For API endpoints, the "HTML" is actually the raw JSON response
        try:
            # Try direct JSON parse first (Nimble may return raw content)
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # If wrapped in HTML tags, extract the JSON body
        try:
            # Strip HTML wrapper if present
            import re as _re
            json_match = _re.search(r'\{.*\}', raw, _re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, AttributeError):
            pass

        logger.debug(f"Nimble response not parseable as JSON, falling back to direct")
        return None

    def discover_chapters(self, page_title: str) -> List[str]:
        """Discover chapter subpages for a work on Wikisource.

        Uses the API to list subpages under the work's main page.
        Returns chapter page titles like "說岳全傳/第一回".
        """
        chapters = []

        # Strategy 1: List subpages via allpages API (with pagination)
        ap_continue = None
        while True:
            params = {
                "action": "query",
                "list": "allpages",
                "apprefix": f"{page_title}/",
                "apnamespace": 0,
                "aplimit": 500,
            }
            if ap_continue:
                params["apcontinue"] = ap_continue

            data = self._api_get(params)
            pages = data.get("query", {}).get("allpages", [])

            for p in pages:
                title = p["title"]
                if any(skip in title for skip in ["討論", "作者", "譯者"]):
                    continue
                chapters.append(title)

            # Check for continuation
            cont = data.get("continue", {})
            if "apcontinue" in cont:
                ap_continue = cont["apcontinue"]
            else:
                break

        if chapters:
            chapters = self._sort_chapters(chapters, page_title)
            return chapters

        # Strategy 2: Parse the main page for links to chapter subpages
        data = self._api_get({
            "action": "parse",
            "page": page_title,
            "prop": "links",
        })
        links = data.get("parse", {}).get("links", [])
        for link in links:
            ns = link.get("ns", -1)
            title = link.get("*", "")
            if ns == 0 and title.startswith(f"{page_title}/"):
                chapters.append(title)

        if chapters:
            chapters = self._sort_chapters(chapters, page_title)
            return chapters

        # Strategy 3: Single-page work — check for sections on the main page
        data = self._api_get({
            "action": "parse",
            "page": page_title,
            "prop": "sections",
        })
        sections = data.get("parse", {}).get("sections", [])
        if sections:
            logger.info(f"Single-page work: {len(sections)} sections on main page")
            # Return section-based IDs: "PAGE_TITLE#section_index"
            for s in sections:
                chapters.append(f"{page_title}#section_{s['index']}")

        return chapters

    def _sort_chapters(self, chapters: List[str], page_title: str) -> List[str]:
        """Sort chapters by their numeric order (回/章/卷 number)."""
        def sort_key(title: str):
            suffix = title[len(page_title) + 1:]  # Strip "TITLE/"
            # Extract leading number (Chinese or Arabic)
            cn_nums = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
                        "百": 100, "千": 1000, "零": 0}
            # Try Arabic number first
            m = re.search(r"(\d+)", suffix)
            if m:
                return int(m.group(1))
            # Parse Chinese numerals
            return self._chinese_num(suffix)

        return sorted(chapters, key=sort_key)

    @staticmethod
    def _chinese_num(text: str) -> int:
        """Parse Chinese numeral string to int (handles up to 999)."""
        cn = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
              "百": 100, "零": 0,
              "〇": 0, "○": 0}
        # Extract just the numeral portion
        m = re.search(r"第([一二三四五六七八九十百零〇○]+)", text)
        if not m:
            return 0
        s = m.group(1)
        result = 0
        current = 0
        for ch in s:
            val = cn.get(ch, 0)
            if val == 100:
                result += (current or 1) * 100
                current = 0
            elif val == 10:
                result += (current or 1) * 10
                current = 0
            else:
                current = val
        result += current
        return result

    def scrape_chapter(self, chapter_page_title: str) -> Optional[ScrapedChapter]:
        """Scrape a single chapter page from Wikisource.

        Handles both regular subpages ("WORK/第一回") and section-based IDs
        ("WORK#section_N") for single-page works.
        """
        # Section-based chapter (single-page work)
        if "#section_" in chapter_page_title:
            return self._scrape_section(chapter_page_title)

        try:
            data = self._api_get({
                "action": "parse",
                "page": chapter_page_title,
                "prop": "text|displaytitle",
            })
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error scraping {chapter_page_title}: {e}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Request error scraping {chapter_page_title}: {e}")
            return None

        parse = data.get("parse")
        if not parse:
            error_info = data.get("error", {}).get("info", "unknown error")
            logger.warning(f"No parse result for {chapter_page_title}: {error_info}")
            return None

        html = parse.get("text", {}).get("*", "")
        if not html:
            logger.warning(f"Empty HTML for {chapter_page_title}")
            return None

        # Extract chapter title from the page title suffix
        parts = chapter_page_title.rsplit("/", 1)
        chapter_title = parts[-1] if len(parts) > 1 else chapter_page_title

        blocks = html_to_blocks(html)
        if not blocks:
            logger.warning(f"No content blocks for {chapter_page_title}")
            return None

        url = f"{WIKISOURCE_BASE_URL}/wiki/{quote(chapter_page_title)}"
        chapter = ScrapedChapter(
            title=chapter_title,
            content=blocks,
            source_url=url,
        )
        chapter.compute_character_count()
        return chapter

    def _scrape_section(self, section_id: str) -> Optional[ScrapedChapter]:
        """Scrape a single section from a single-page work."""
        page_title, section_part = section_id.split("#section_", 1)
        section_index = int(section_part)

        try:
            data = self._api_get({
                "action": "parse",
                "page": page_title,
                "prop": "text|sections",
                "section": section_index,
            })
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            logger.error(f"Error scraping section {section_id}: {e}")
            return None

        parse = data.get("parse")
        if not parse:
            return None

        # Get section title from sections list
        sections = parse.get("sections", [])
        section_title = ""
        for s in sections:
            if str(s.get("index")) == str(section_index):
                section_title = s.get("line", "")
                break
        if not section_title:
            section_title = parse.get("displaytitle", f"Section {section_index}")
            # Strip HTML from displaytitle
            from bs4 import BeautifulSoup as _BS
            section_title = _BS(section_title, "lxml").get_text()

        html = parse.get("text", {}).get("*", "")
        if not html:
            return None

        blocks = html_to_blocks(html)
        if not blocks:
            return None

        url = f"{WIKISOURCE_BASE_URL}/wiki/{quote(page_title)}#section_{section_index}"
        chapter = ScrapedChapter(
            title=section_title,
            content=blocks,
            source_url=url,
        )
        chapter.compute_character_count()
        return chapter

    def get_work_url(self, page_title: str) -> str:
        return f"{WIKISOURCE_BASE_URL}/wiki/{quote(page_title)}"
