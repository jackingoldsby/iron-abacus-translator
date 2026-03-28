#!/usr/bin/env python3
"""
Metropolitan Museum Open Access search source.

Adapted from crimson_folio/covers/searcher.py — searches the Met's Open Access
collection for public domain Chinese period artwork.
"""

import logging
from typing import List

import requests

from config.defaults import DEFAULT_TIMEOUT
from models.portfolio import ArtworkCandidate
from sources.base import BaseSource

logger = logging.getLogger(__name__)

MET_API = "https://collectionapi.metmuseum.org/public/collection/v1"


class MetMuseumSource(BaseSource):
    """Search Metropolitan Museum Open Access collection."""

    source_name = "met_museum"

    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "AmberInkstone/0.1 (period artwork curator; scholarly research)"
        )

    def search(self, query: str, limit: int = 10) -> List[ArtworkCandidate]:
        """Search Met Museum for public domain Chinese artwork.

        Only returns items flagged as Open Access / public domain.
        """
        try:
            # Step 1: Search for object IDs
            resp = self.session.get(
                f"{MET_API}/search",
                params={
                    "q": query,
                    "isPublicDomain": "true",
                    "hasImages": "true",
                    "departmentId": 6,  # Asian Art department
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            object_ids = data.get("objectIDs", [])
            if not object_ids:
                return []

            # Step 2: Fetch details for top candidates
            results = []
            for obj_id in object_ids[:limit * 2]:  # Extra to cover skips
                if len(results) >= limit:
                    break
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

                    results.append(ArtworkCandidate(
                        url=primary_image,
                        title=obj.get("title", "Untitled"),
                        source_api=self.source_name,
                        license="CC0 (Public Domain)",
                        width=0,  # Met API doesn't provide dimensions in search
                        height=0,
                        artist=obj.get("artistDisplayName", ""),
                        medium=obj.get("medium", ""),
                        date_text=obj.get("objectDate", ""),
                        thumbnail_url=obj.get("primaryImageSmall", ""),
                        search_query=query,
                    ))
                except Exception:
                    continue

            logger.info(f"Met Museum search '{query}': {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Met Museum search failed: {e}")
            return []
