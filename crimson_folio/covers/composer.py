#!/usr/bin/env python3
"""
Cover Composer — assemble final cover image from artwork + title overlay.

Takes a period artwork image and composites it with title text
(English + Chinese) and author name to create an EPUB cover.
"""

import logging
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from config.defaults import COVER_OUTPUT_WIDTH, COVER_OUTPUT_HEIGHT

logger = logging.getLogger(__name__)

# Try to find a system font with CJK support
_CJK_FONT_PATHS = [
    "/System/Library/Fonts/STHeiti Light.ttc",       # macOS
    "/System/Library/Fonts/PingFang.ttc",            # macOS
    "/System/Library/Fonts/Hiragino Sans GB.ttc",    # macOS
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",  # Linux
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", # Linux
]

_SERIF_FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Baskerville.ttc",      # macOS — elegant classical
    "/System/Library/Fonts/Supplemental/Didot.ttc",            # macOS — refined alternative
    "/System/Library/Fonts/Supplemental/Hoefler Text.ttc",     # macOS — literary
    "/System/Library/Fonts/Times.ttc",                         # macOS — fallback
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",  # macOS — fallback
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",        # Linux
]


def _find_font(paths: list, size: int) -> ImageFont.FreeTypeFont:
    """Find and load the first available font from paths."""
    for path in paths:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


class CoverComposer:
    """Compose a cover image from artwork and text."""

    def __init__(
        self,
        width: int = COVER_OUTPUT_WIDTH,
        height: int = COVER_OUTPUT_HEIGHT,
    ):
        self.width = width
        self.height = height

    def compose(
        self,
        artwork_path: Path,
        title_en: str,
        title_zh: str = "",
        subtitle: str = "",
        author_en: str = "",
        author_zh: str = "",
        translator: str = "",
        output_path: Optional[Path] = None,
    ) -> Path:
        """Compose final cover from artwork and text.

        The artwork is scaled to fill the cover dimensions while preserving
        aspect ratio (crop to fit). A semi-transparent gradient overlay
        is applied at top and bottom to ensure text readability.

        Args:
            artwork_path: Path to the source artwork image
            title_en: English title
            title_zh: Chinese title (optional)
            author_en: English author name (optional)
            author_zh: Chinese author name (optional)
            output_path: Where to save the composed cover. If None, saves
                         next to artwork with '_cover' suffix.

        Returns:
            Path to the composed cover image
        """
        if output_path is None:
            output_path = artwork_path.parent / f"{artwork_path.stem}_cover.jpg"

        # Load and resize artwork to fill cover dimensions
        with Image.open(artwork_path) as artwork:
            artwork = artwork.convert("RGB")
            cover = self._fit_artwork(artwork)

        # Apply gradient overlay for text readability
        cover = self._apply_gradient(cover)

        # Add subtle border frame
        cover = self._add_border(cover)

        # Draw text
        draw = ImageDraw.Draw(cover)
        self._draw_title(draw, title_en, title_zh, subtitle)
        self._draw_author(draw, author_en, author_zh, translator)

        # Add publisher logo at bottom center
        cover = self._add_logo(cover)

        # Save
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cover.save(str(output_path), "JPEG", quality=92)
        logger.info(f"Composed cover: {output_path} ({self.width}x{self.height})")
        return output_path

    def _fit_artwork(self, artwork: Image.Image) -> Image.Image:
        """Scale and crop artwork to fill cover dimensions, with warmth enhancement."""
        from PIL import ImageEnhance

        # Warm up: boost contrast and saturation
        artwork = ImageEnhance.Contrast(artwork).enhance(1.15)
        artwork = ImageEnhance.Color(artwork).enhance(1.2)
        artwork = ImageEnhance.Brightness(artwork).enhance(1.05)

        aw, ah = artwork.size
        target_ratio = self.width / self.height
        artwork_ratio = aw / ah

        if artwork_ratio > target_ratio:
            # Artwork is wider — scale by height, crop width
            new_h = self.height
            new_w = int(aw * (self.height / ah))
        else:
            # Artwork is taller — scale by width, crop height
            new_w = self.width
            new_h = int(ah * (self.width / aw))

        artwork = artwork.resize((new_w, new_h), Image.LANCZOS)

        # Center crop
        left = (new_w - self.width) // 2
        top = (new_h - self.height) // 2
        artwork = artwork.crop((left, top, left + self.width, top + self.height))
        return artwork

    def _apply_gradient(self, image: Image.Image) -> Image.Image:
        """Apply semi-transparent dark gradient at top and bottom for text contrast."""
        overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Top gradient (for title + subtitle) — covers top 45%
        gradient_height = int(self.height * 0.45)
        for y in range(gradient_height):
            progress = 1 - y / gradient_height
            # Ease-out curve for smoother transition
            alpha = int(210 * (progress ** 0.7))
            draw.line([(0, y), (self.width, y)], fill=(10, 5, 0, alpha))

        # Bottom gradient (for author) — covers bottom 25%
        bottom_start = int(self.height * 0.75)
        bottom_height = self.height - bottom_start
        for y in range(bottom_height):
            progress = y / bottom_height
            alpha = int(200 * (progress ** 0.7))
            draw.line(
                [(0, bottom_start + y), (self.width, bottom_start + y)],
                fill=(10, 5, 0, alpha),
            )

        # Composite
        image = image.convert("RGBA")
        image = Image.alpha_composite(image, overlay)
        return image.convert("RGB")

    def _add_logo(self, cover: Image.Image) -> Image.Image:
        """Add publisher logo at bottom center with white circular backing."""
        logo_path = Path(__file__).parent.parent / "assets" / "iron_abacus_logo.png"
        if not logo_path.exists():
            return cover

        with Image.open(logo_path) as logo:
            logo = logo.convert("RGBA")
            # Scale logo larger and center
            logo_w = int(self.width * 0.26)  # ~416px at 1600w
            ratio = logo_w / logo.width
            logo_h = int(logo.height * ratio)
            logo = logo.resize((logo_w, logo_h), Image.LANCZOS)

            # Position at bottom center
            x = (self.width - logo_w) // 2
            y = int(self.height * 0.96) - logo_h

            # White backing: omega shape — circle on top, rectangle below, overlapping
            # Circle is symmetric around the seal circle in the logo
            # Exact seal circle center (widest horizontal span): x=0.4996, y=0.4466
            # Circle radius from widest span: 0.3490 of image height
            seal_cx = x + int(logo_w * 0.4996)
            seal_cy = y + int(logo_h * 0.4466)
            seal_r = int(logo_h * 0.3490) + 10  # symmetric white band, tighter

            # Rectangle below, narrower, overlapping bottom of circle
            rect_cy = y + int(logo_h * 0.88)
            rect_h = int(logo_h * 0.16)
            rect_w = int(logo_w * 0.38)  # narrower
            rect_top = rect_cy - rect_h // 2

            backing = Image.new("RGBA", cover.size, (0, 0, 0, 0))
            backing_draw = ImageDraw.Draw(backing)
            # Both shapes drawn — they merge where they overlap
            backing_draw.ellipse(
                [seal_cx - seal_r, seal_cy - seal_r,
                 seal_cx + seal_r, seal_cy + seal_r],
                fill=(255, 255, 255, 215)
            )
            backing_draw.rounded_rectangle(
                [seal_cx - rect_w // 2, rect_top,
                 seal_cx + rect_w // 2, rect_top + rect_h],
                radius=8,
                fill=(255, 255, 255, 215)
            )

            # Composite: backing then logo
            cover = cover.convert("RGBA")
            cover = Image.alpha_composite(cover, backing)
            cover.paste(logo, (x, y), logo)
            cover = cover.convert("RGB")

        return cover

    def _add_border(self, image: Image.Image) -> Image.Image:
        """Add a subtle decorative border frame."""
        draw = ImageDraw.Draw(image)
        margin = int(self.width * 0.03)  # ~48px at 1600w
        inner_margin = margin + int(self.width * 0.005)  # thin inner line

        # Outer border — dark semi-transparent
        border_color = (180, 160, 120)  # warm gold-brown
        draw.rectangle(
            [margin, margin, self.width - margin, self.height - margin],
            outline=border_color, width=2,
        )
        # Inner border — thinner
        draw.rectangle(
            [inner_margin, inner_margin,
             self.width - inner_margin, self.height - inner_margin],
            outline=border_color, width=1,
        )
        return image

    def _draw_title(
        self, draw: ImageDraw.Draw, title_en: str, title_zh: str,
        subtitle: str = ""
    ) -> None:
        """Draw title text in the upper portion of the cover."""
        # English title — large serif font
        en_size = self.width // 12  # ~133px at 1600w
        en_font = _find_font(_SERIF_FONT_PATHS, en_size)

        # Word-wrap if too long
        lines = self._wrap_text(title_en, en_font, int(self.width * 0.85), draw)

        y = int(self.height * 0.05)
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=en_font)
            text_w = bbox[2] - bbox[0]
            x = (self.width - text_w) // 2
            # Shadow for readability
            draw.text((x + 2, y + 2), line, fill=(0, 0, 0, 180), font=en_font)
            draw.text((x, y), line, fill=(255, 255, 255), font=en_font)
            y += int(en_size * 1.3)

        # Chinese title — smaller, below English
        if title_zh:
            zh_size = self.width // 18  # ~89px at 1600w
            zh_font = _find_font(_CJK_FONT_PATHS, zh_size)
            bbox = draw.textbbox((0, 0), title_zh, font=zh_font)
            text_w = bbox[2] - bbox[0]
            x = (self.width - text_w) // 2
            y += int(zh_size * 0.3)
            draw.text((x + 2, y + 2), title_zh, fill=(0, 0, 0, 160), font=zh_font)
            draw.text((x, y), title_zh, fill=(220, 220, 220), font=zh_font)
            y += int(zh_size * 1.4)

        # Subtitle — smaller, each explicit line centered separately
        if subtitle:
            sub_size = self.width // 30  # ~53px at 1600w
            sub_font = _find_font(_SERIF_FONT_PATHS, sub_size)
            y += int(sub_size * 0.5)
            # Split on explicit newlines first, then word-wrap each
            for raw_line in subtitle.split('\n'):
                wrapped = self._wrap_text(raw_line.strip(), sub_font, int(self.width * 0.75), draw)
                for line in wrapped:
                    bbox = draw.textbbox((0, 0), line, font=sub_font)
                    text_w = bbox[2] - bbox[0]
                    x = (self.width - text_w) // 2
                    draw.text((x + 1, y + 1), line, fill=(0, 0, 0, 140), font=sub_font)
                    draw.text((x, y), line, fill=(200, 200, 200), font=sub_font)
                    y += int(sub_size * 1.3)
                y += int(sub_size * 0.2)  # extra gap between subtitle lines

    def _draw_author(
        self, draw: ImageDraw.Draw, author_en: str, author_zh: str,
        translator: str = ""
    ) -> None:
        """Draw author name in the lower portion of the cover."""
        if not author_en and not author_zh and not translator:
            return

        y = int(self.height * 0.68)

        if author_en:
            en_size = self.width // 22  # ~73px at 1600w
            en_font = _find_font(_SERIF_FONT_PATHS, en_size)
            bbox = draw.textbbox((0, 0), author_en, font=en_font)
            text_w = bbox[2] - bbox[0]
            x = (self.width - text_w) // 2
            draw.text((x + 1, y + 1), author_en, fill=(0, 0, 0, 160), font=en_font)
            draw.text((x, y), author_en, fill=(255, 255, 255), font=en_font)
            y += int(en_size * 1.3)

        if author_zh:
            zh_size = self.width // 28  # ~57px at 1600w
            zh_font = _find_font(_CJK_FONT_PATHS, zh_size)
            bbox = draw.textbbox((0, 0), author_zh, font=zh_font)
            text_w = bbox[2] - bbox[0]
            x = (self.width - text_w) // 2
            draw.text((x + 1, y + 1), author_zh, fill=(0, 0, 0, 140), font=zh_font)
            draw.text((x, y), author_zh, fill=(200, 200, 200), font=zh_font)
            y += int(zh_size * 1.3)

        if translator:
            tr_size = self.width // 32  # ~50px at 1600w
            tr_font = _find_font(_SERIF_FONT_PATHS, tr_size)
            tr_text = f"Translated by {translator}"
            bbox = draw.textbbox((0, 0), tr_text, font=tr_font)
            text_w = bbox[2] - bbox[0]
            x = (self.width - text_w) // 2
            y += int(tr_size * 0.5)
            draw.text((x + 1, y + 1), tr_text, fill=(0, 0, 0, 120), font=tr_font)
            draw.text((x, y), tr_text, fill=(180, 180, 180), font=tr_font)

    @staticmethod
    def _wrap_text(
        text: str,
        font: ImageFont.FreeTypeFont,
        max_width: int,
        draw: ImageDraw.Draw,
    ) -> list:
        """Word-wrap text to fit within max_width pixels."""
        words = text.split()
        lines = []
        current_line = ""

        for word in words:
            test = f"{current_line} {word}".strip()
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current_line = test
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word

        if current_line:
            lines.append(current_line)

        return lines or [text]
