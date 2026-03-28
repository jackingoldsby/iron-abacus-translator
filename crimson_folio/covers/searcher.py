#!/usr/bin/env python3
"""
Cover Image Searcher — Wikimedia Commons and Met Museum API search.

Searches structured, clearly-licensed sources for public domain artwork
suitable as EPUB cover images.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

# Wikimedia Commons API
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
# Met Museum Open Access API
MET_API = "https://collectionapi.metmuseum.org/public/collection/v1"


@dataclass
class ImageResult:
    """A candidate cover image from search."""
    url: str
    title: str
    source: str
    license: str
    width: int
    height: int
    thumbnail_url: str = ""


class CoverSearcher:
    """Search public domain image sources for cover artwork."""

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "CrimsonFolio/0.1 (EPUB builder; jacki@example.com)"
        )

    def search_wikimedia(self, query: str, limit: int = 5) -> List[ImageResult]:
        """Search Wikimedia Commons for genuine historical artwork.

        Filters for actual period paintings, scrolls, and prints —
        excludes modern illustrations, AI art, and reproductions.

        Args:
            query: Search query string
            limit: Maximum number of results

        Returns:
            List of ImageResult objects
        """
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrnamespace": 6,  # File namespace
            "gsrsearch": f"{query} filetype:bitmap",
            "gsrlimit": limit * 2,  # Fetch extra to allow filtering
            "prop": "imageinfo|categories",
            "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": 400,
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

                # Filter out modern/AI content by checking categories and metadata
                title_lower = page.get("title", "").lower()
                categories_text = " ".join(
                    c.get("title", "") for c in page.get("categories", [])
                ).lower()
                artist_info = extmeta.get("Artist", {}).get("value", "").lower()
                desc = extmeta.get("ImageDescription", {}).get("value", "").lower()

                # Reject obvious modern/AI content
                reject_signals = [
                    "ai generated", "artificial intelligence", "digital art",
                    "illustration", "manga", "anime", "fan art", "deviantart",
                    "artstation", "pixiv", "modern", "contemporary art",
                    "stable diffusion", "midjourney", "dall-e",
                ]
                combined_text = f"{title_lower} {categories_text} {artist_info} {desc}"
                if any(signal in combined_text for signal in reject_signals):
                    continue

                results.append(ImageResult(
                    url=imageinfo.get("url", ""),
                    title=page.get("title", "").replace("File:", ""),
                    source="wikimedia_commons",
                    license=license_info,
                    width=width,
                    height=height,
                    thumbnail_url=imageinfo.get("thumburl", ""),
                ))

            results = results[:limit]
            logger.info(f"Wikimedia search '{query}': {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Wikimedia search failed: {e}")
            return []

    def search_met_museum(self, query: str, limit: int = 5) -> List[ImageResult]:
        """Search Metropolitan Museum Open Access collection.

        Args:
            query: Search query string
            limit: Maximum number of results

        Returns:
            List of ImageResult objects (only Open Access items)
        """
        try:
            # Step 1: Search for object IDs
            resp = self.session.get(
                f"{MET_API}/search",
                params={"q": query, "isPublicDomain": "true", "hasImages": "true"},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            object_ids = data.get("objectIDs", [])
            if not object_ids:
                return []

            # Step 2: Fetch details for top results
            results = []
            for obj_id in object_ids[:limit]:
                try:
                    obj_resp = self.session.get(
                        f"{MET_API}/objects/{obj_id}",
                        timeout=self.timeout,
                    )
                    obj_resp.raise_for_status()
                    obj = obj_resp.json()

                    if not obj.get("isPublicDomain"):
                        continue

                    primary_image = obj.get("primaryImage", "")
                    if not primary_image:
                        continue

                    results.append(ImageResult(
                        url=primary_image,
                        title=obj.get("title", "Untitled"),
                        source="met_museum",
                        license="CC0 (Public Domain)",
                        width=0,  # Met API doesn't provide dimensions in search
                        height=0,
                        thumbnail_url=obj.get("primaryImageSmall", ""),
                    ))
                except Exception:
                    continue

            logger.info(f"Met Museum search '{query}': {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Met Museum search failed: {e}")
            return []

    def search_all(self, query: str, limit: int = 5) -> List[ImageResult]:
        """Search all configured sources.

        Args:
            query: Search query string
            limit: Max results per source

        Returns:
            Combined results from all sources
        """
        results = []
        results.extend(self.search_wikimedia(query, limit))
        results.extend(self.search_met_museum(query, limit))
        return results
