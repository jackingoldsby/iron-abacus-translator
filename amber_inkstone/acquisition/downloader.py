#!/usr/bin/env python3
"""
Artwork Downloader — fetch, validate, cache, and thumbnail artwork images.

Adapted from crimson_folio/covers/downloader.py for period-level portfolio caching.
Cache layout: ~/.amber_inkstone/images/{period_slug}/{image_id}.jpg
"""

import hashlib
import logging
from pathlib import Path
from typing import Optional

import requests
from PIL import Image

from acquisition.validator import validate_image
from config.defaults import DEFAULT_CACHE_DIR, MAX_DOWNLOAD_SIZE, THUMBNAIL_SIZE
from models.portfolio import ArtworkCandidate, ArtworkImage

logger = logging.getLogger(__name__)


class ArtworkDownloader:
    """Download and cache artwork images by period."""

    def __init__(self, cache_dir: Optional[Path] = None, timeout: int = 30):
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "AmberInkstone/0.1 (period artwork curator; scholarly research)"
        )

    def download(
        self,
        candidate: ArtworkCandidate,
        period_slug: str,
        period_label: str,
    ) -> Optional[ArtworkImage]:
        """Download an artwork candidate and store it in the period cache.

        Args:
            candidate: The artwork to download
            period_slug: Canonical period slug for directory organization
            period_label: Human-readable period label

        Returns:
            ArtworkImage if successful, None otherwise
        """
        image_id = hashlib.md5(candidate.url.encode()).hexdigest()
        period_dir = self.cache_dir / period_slug
        period_dir.mkdir(parents=True, exist_ok=True)

        # Check cache
        for ext in (".jpg", ".jpeg", ".png"):
            cached = period_dir / f"{image_id}{ext}"
            if cached.exists():
                logger.info(f"Cache hit: {cached.name}")
                return self._build_artwork_image(
                    candidate, image_id, period_slug, period_label,
                    str(cached), self._thumbnail_path(cached),
                )

        try:
            resp = self.session.get(candidate.url, timeout=self.timeout, stream=True)
            resp.raise_for_status()

            # Determine extension
            content_type = resp.headers.get("content-type", "")
            ext = ".jpg"
            if "png" in content_type:
                ext = ".png"

            output_path = period_dir / f"{image_id}{ext}"

            # Stream download with size limit
            downloaded = 0
            with open(output_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    downloaded += len(chunk)
                    if downloaded > MAX_DOWNLOAD_SIZE:
                        logger.warning(f"Image too large (>{MAX_DOWNLOAD_SIZE // (1024*1024)}MB)")
                        output_path.unlink(missing_ok=True)
                        return None
                    f.write(chunk)

            # Validate
            if not validate_image(output_path):
                output_path.unlink(missing_ok=True)
                return None

            # Generate thumbnail
            thumb_path = self._generate_thumbnail(output_path)

            # Get actual dimensions
            width, height = 0, 0
            try:
                with Image.open(output_path) as img:
                    width, height = img.size
            except Exception:
                pass

            logger.info(f"Downloaded: {output_path.name} ({downloaded / 1024:.1f} KB)")

            return self._build_artwork_image(
                candidate, image_id, period_slug, period_label,
                str(output_path), str(thumb_path) if thumb_path else "",
                width=width, height=height,
            )

        except Exception as e:
            logger.error(f"Download failed for {candidate.url}: {e}")
            return None

    def _generate_thumbnail(self, image_path: Path) -> Optional[Path]:
        """Generate a thumbnail for the image."""
        try:
            thumb_path = image_path.parent / f"{image_path.stem}_thumb{image_path.suffix}"
            with Image.open(image_path) as img:
                img.thumbnail(THUMBNAIL_SIZE)
                img.save(thumb_path)
            return thumb_path
        except Exception as e:
            logger.warning(f"Thumbnail generation failed: {e}")
            return None

    @staticmethod
    def _thumbnail_path(cached_path: Path) -> str:
        thumb = cached_path.parent / f"{cached_path.stem}_thumb{cached_path.suffix}"
        return str(thumb) if thumb.exists() else ""

    @staticmethod
    def _build_artwork_image(
        candidate: ArtworkCandidate,
        image_id: str,
        period_slug: str,
        period_label: str,
        cached_path: str,
        thumbnail_path: str,
        width: int = 0,
        height: int = 0,
    ) -> ArtworkImage:
        return ArtworkImage(
            image_id=image_id,
            period_slug=period_slug,
            period_label=period_label,
            source_url=candidate.url,
            source_api=candidate.source_api,
            title=candidate.title,
            artist=candidate.artist,
            medium=candidate.medium,
            date_text=candidate.date_text,
            license=candidate.license,
            width=width or candidate.width,
            height=height or candidate.height,
            cached_path=cached_path,
            thumbnail_path=thumbnail_path,
            search_query=candidate.search_query,
        )
