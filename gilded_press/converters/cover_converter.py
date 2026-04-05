"""Convert cover images to KDP specifications."""

import logging
from pathlib import Path
from typing import Optional

from PIL import Image

from config.defaults import (
    KDP_COVER_WIDTH, KDP_COVER_HEIGHT, KDP_COVER_DPI,
    KDP_COVER_MAX_SIZE_MB, KDP_COVER_LIGHT_BG_BORDER_PX,
    KDP_COVER_LIGHT_BG_BORDER_COLOR,
)

logger = logging.getLogger(__name__)


def convert_cover(
    input_path: Path,
    output_path: Optional[Path] = None,
    width: int = KDP_COVER_WIDTH,
    height: int = KDP_COVER_HEIGHT,
) -> Path:
    """Convert a cover image to KDP specifications.

    - Resize to exact dimensions (2560×1600)
    - Convert to RGB JPEG
    - Set DPI to 300
    - Add gray border if background is light
    - Validate file size < 50MB

    Args:
        input_path: Source cover image (any format)
        output_path: Destination JPEG path
        width: Target width (default 1600)
        height: Target height (default 2560)

    Returns:
        Path to the KDP-compliant cover JPEG
    """
    if output_path is None:
        output_path = input_path.parent / f"{input_path.stem}_kdp.jpg"

    with Image.open(input_path) as img:
        # Convert to RGB (strip alpha)
        if img.mode != "RGB":
            img = img.convert("RGB")

        # Resize to exact KDP dimensions
        img = img.resize((width, height), Image.LANCZOS)

        # Check if background is light — add gray border if so
        if _has_light_background(img):
            img = _add_border(img)
            logger.info("  Added gray border (light background detected)")

        # Save as JPEG with high quality, 300 DPI
        img.save(
            str(output_path),
            "JPEG",
            quality=95,
            dpi=(KDP_COVER_DPI, KDP_COVER_DPI),
        )

    # Validate file size
    size_mb = output_path.stat().st_size / (1024 * 1024)
    if size_mb > KDP_COVER_MAX_SIZE_MB:
        logger.warning(f"  Cover is {size_mb:.1f} MB (max {KDP_COVER_MAX_SIZE_MB} MB)")
    else:
        logger.info(f"  Cover: {width}×{height}, {size_mb:.1f} MB, RGB JPEG")

    return output_path


def validate_cover(path: Path) -> dict:
    """Validate an existing cover image against KDP specs.

    Returns:
        Dict with 'valid' bool and 'issues' list.
    """
    issues = []

    if not path.exists():
        return {"valid": False, "issues": ["File not found"]}

    with Image.open(path) as img:
        w, h = img.size

        if img.mode != "RGB":
            issues.append(f"Color space is {img.mode}, must be RGB")

        if w < 625 or h < 1000:
            issues.append(f"Too small: {w}×{h} (min 625×1000)")

        if w > 10000 or h > 10000:
            issues.append(f"Too large: {w}×{h} (max 10000×10000)")

        ratio = h / w
        if ratio < 1.5 or ratio > 1.8:
            issues.append(f"Aspect ratio {ratio:.2f} (ideal 1.6:1)")

    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > KDP_COVER_MAX_SIZE_MB:
        issues.append(f"File too large: {size_mb:.1f} MB (max {KDP_COVER_MAX_SIZE_MB})")

    suffix = path.suffix.lower()
    if suffix not in (".jpg", ".jpeg", ".tif", ".tiff"):
        issues.append(f"Format {suffix} not accepted (must be JPEG or TIFF)")

    return {"valid": len(issues) == 0, "issues": issues}


def _has_light_background(img: Image.Image, sample_size: int = 20) -> bool:
    """Check if the image has a light background by sampling edges."""
    w, h = img.size
    samples = []
    for x in range(sample_size):
        for y in [0, 1, h - 2, h - 1]:
            samples.append(img.getpixel((x, y)))
        for y in range(sample_size):
            samples.append(img.getpixel((0, y)))
            samples.append(img.getpixel((w - 1, y)))

    avg_brightness = sum(sum(rgb) / 3 for rgb in samples) / len(samples)
    return avg_brightness > 220


def _add_border(img: Image.Image) -> Image.Image:
    """Add a thin gray border around the image."""
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    w, h = img.size
    b = KDP_COVER_LIGHT_BG_BORDER_PX
    color = KDP_COVER_LIGHT_BG_BORDER_COLOR
    draw.rectangle([0, 0, w - 1, h - 1], outline=color, width=b)
    return img
