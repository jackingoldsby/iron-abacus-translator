#!/usr/bin/env python3
"""
Cover Image Downloader — fetch and validate candidate cover images.

Downloads images from Wikimedia Commons or Met Museum, validates
dimensions and format, and caches locally.
"""

import hashlib
import logging
from pathlib import Path
from typing import Optional

import requests
from PIL import Image

from config.defaults import (
    COVER_MIN_WIDTH,
    COVER_MIN_HEIGHT,
    DEFAULT_COVER_CACHE_DIR,
)

logger = logging.getLogger(__name__)


class CoverDownloader:
    """Download and validate cover image candidates."""

    def __init__(self, cache_dir: Optional[Path] = None, timeout: int = 30):
        self.cache_dir = cache_dir or DEFAULT_COVER_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "CrimsonFolio/0.1 (EPUB builder; jacki@example.com)"
        )

    def download(self, url: str, work_number: str = "") -> Optional[Path]:
        """Download an image and cache it locally.

        Args:
            url: Image URL to download
            work_number: Work identifier for cache naming

        Returns:
            Path to cached image file, or None if download/validation failed
        """
        # Check cache first
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        cache_key = f"{work_number}_{url_hash}" if work_number else url_hash

        # Check existing cache entries
        for ext in (".jpg", ".jpeg", ".png"):
            cached = self.cache_dir / f"{cache_key}{ext}"
            if cached.exists():
                logger.info(f"Using cached cover: {cached.name}")
                return cached

        try:
            resp = self.session.get(url, timeout=self.timeout, stream=True)
            resp.raise_for_status()

            # Determine file extension from content type
            content_type = resp.headers.get("content-type", "")
            ext = ".jpg"
            if "png" in content_type:
                ext = ".png"
            elif "jpeg" in content_type or "jpg" in content_type:
                ext = ".jpg"

            output_path = self.cache_dir / f"{cache_key}{ext}"

            # Download with size limit (50MB)
            max_size = 50 * 1024 * 1024
            downloaded = 0
            with open(output_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    downloaded += len(chunk)
                    if downloaded > max_size:
                        logger.warning(f"Image too large (>{max_size // (1024*1024)}MB): {url}")
                        output_path.unlink(missing_ok=True)
                        return None
                    f.write(chunk)

            # Validate the downloaded image
            if self.validate(output_path):
                logger.info(f"Downloaded cover: {output_path.name} ({downloaded / 1024:.1f} KB)")
                return output_path
            else:
                output_path.unlink(missing_ok=True)
                return None

        except Exception as e:
            logger.error(f"Download failed for {url}: {e}")
            return None

    def validate(self, image_path: Path) -> bool:
        """Validate an image meets cover requirements.

        Checks:
        - File is a valid image (can be opened by Pillow)
        - Minimum resolution (600x800)
        - Reasonable aspect ratio for book cover

        Args:
            image_path: Path to image file

        Returns:
            True if image is suitable for cover use
        """
        try:
            with Image.open(image_path) as img:
                width, height = img.size

                if width < COVER_MIN_WIDTH or height < COVER_MIN_HEIGHT:
                    logger.info(
                        f"Image too small: {width}x{height} "
                        f"(need {COVER_MIN_WIDTH}x{COVER_MIN_HEIGHT})"
                    )
                    return False

                # Check aspect ratio — should be roughly portrait (taller than wide)
                # Allow landscape art since we can crop/letterbox
                aspect = width / height
                if aspect > 2.0:  # Too wide/panoramic
                    logger.info(f"Aspect ratio too wide: {aspect:.2f}")
                    return False

                return True

        except Exception as e:
            logger.error(f"Image validation failed for {image_path}: {e}")
            return False
