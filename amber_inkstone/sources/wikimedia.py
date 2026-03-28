#!/usr/bin/env python3
"""
Wikimedia Commons search source for period artwork.

Adapted from crimson_folio/covers/searcher.py — searches Wikimedia Commons
for genuine historical Chinese artwork, filtering out modern/AI content.
"""

import logging
from typing import List

import requests

from config.defaults import DEFAULT_TIMEOUT
from models.portfolio import ArtworkCandidate
from sources.base import BaseSource

logger = logging.getLogger(__name__)

COMMONS_API = "https://commons.wikimedia.org/w/api.php"

# Signals that indicate modern, AI, or non-period artwork
REJECT_SIGNALS = [
    "ai generated", "artificial intelligence", "digital art",
    "illustration", "manga", "anime", "fan art", "deviantart",
    "artstation", "pixiv", "modern", "contemporary art",
    "stable diffusion", "midjourney", "dall-e", "computer generated",
    "photo", "photograph", "screenshot",
]


class WikimediaSource(BaseSource):
    """Search Wikimedia Commons for genuine historical artwork."""

    source_name = "wikimedia_commons"

    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "AmberInkstone/0.1 (period artwork curator; scholarly research)"
        )

    def search(self, query: str, limit: int = 10) -> List[ArtworkCandidate]:
        """Search Wikimedia Commons for period artwork.

        Filters for actual paintings, scrolls, and prints — excludes modern
        illustrations, AI art, photographs, and reproductions.
        """
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrnamespace": 6,  # File namespace
            "gsrsearch": f"{query} filetype:bitmap",
            "gsrlimit": limit * 3,  # Fetch extra to allow filtering
            "prop": "imageinfo|categories",
            "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": 300,  # Thumbnail width
            "cllimit": 10,
        }

        try:
            resp = self.session.get(COMMONS_API, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()

            results = []
            pages = data.get("query", {}).get("pages", {})

            for page in pages.values():
                imageinfo = page.get("imageinfo", [{}])[0]
                if not imageinfo:
                    continue

                extmeta = imageinfo.get("extmetadata", {})
                license_info = extmeta.get("LicenseShortName", {}).get("value", "unknown")
                width = imageinfo.get("width", 0)
                height = imageinfo.get("height", 0)

                if width < 400 or height < 400:
                    continue

                # Build text for reject-signal checking
                title_lower = page.get("title", "").lower()
                categories_text = " ".join(
                    c.get("title", "") for c in page.get("categories", [])
                ).lower()
                artist_info = extmeta.get("Artist", {}).get("value", "").lower()
                desc = extmeta.get("ImageDescription", {}).get("value", "").lower()
                combined_text = f"{title_lower} {categories_text} {artist_info} {desc}"

                if any(signal in combined_text for signal in REJECT_SIGNALS):
                    continue

                # Extract metadata fields
                artist_raw = extmeta.get("Artist", {}).get("value", "")
                date_raw = extmeta.get("DateTimeOriginal", {}).get("value", "")
                medium_raw = extmeta.get("ObjectName", {}).get("value", "")

                results.append(ArtworkCandidate(
                    url=imageinfo.get("url", ""),
                    title=page.get("title", "").replace("File:", ""),
                    source_api=self.source_name,
                    license=license_info,
                    width=width,
                    height=height,
                    artist=artist_raw[:200],  # Truncate HTML-heavy artist fields
                    medium=medium_raw[:200],
                    date_text=date_raw[:100],
                    thumbnail_url=imageinfo.get("thumburl", ""),
                    search_query=query,
                ))

            results = results[:limit]
            logger.info(f"Wikimedia search '{query}': {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Wikimedia search failed: {e}")
            return []
