#!/usr/bin/env python3
"""
Image validator — checks that downloaded images meet portfolio requirements.
"""

import logging
from pathlib import Path

from PIL import Image

from config.defaults import IMAGE_MAX_ASPECT_RATIO, IMAGE_MIN_HEIGHT, IMAGE_MIN_WIDTH

logger = logging.getLogger(__name__)


def validate_image(image_path: Path) -> bool:
    """Validate an image meets portfolio requirements.

    Checks:
    - File is a valid image (opens with Pillow)
    - Minimum resolution (600x800)
    - Reasonable aspect ratio (not panoramic)

    Args:
        image_path: Path to image file

    Returns:
        True if image is suitable for portfolio
    """
    try:
        with Image.open(image_path) as img:
            width, height = img.size

            if width < IMAGE_MIN_WIDTH or height < IMAGE_MIN_HEIGHT:
                logger.info(
                    f"Image too small: {width}x{height} "
                    f"(need {IMAGE_MIN_WIDTH}x{IMAGE_MIN_HEIGHT})"
                )
                return False

            aspect = max(width, height) / min(width, height)
            if aspect > IMAGE_MAX_ASPECT_RATIO:
                logger.info(f"Aspect ratio too extreme: {aspect:.2f}")
                return False

            return True

    except Exception as e:
        logger.error(f"Image validation failed for {image_path}: {e}")
        return False
