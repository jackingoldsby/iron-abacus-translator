#!/usr/bin/env python3
"""
EPUB3 Builder for Translated Wuxia Novels

Produces Kindle-ready EPUB3 files with:
- Popup footnotes (EPUB3 aside + epub:type="footnote")
- Content-type-aware formatting (narrative, dialogue, verse, document, thought)
- Bilingual title page
- NCX + EPUB3 nav table of contents
- Glossary appendix
- Optional cover image

Usage:
    from builders.epub_builder import EpubBuilder

    builder = EpubBuilder()
    builder.build(translated_json_path, output_epub_path)
"""

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ebooklib import epub

from config.defaults import DEFAULT_CSS_PATH, DEFAULT_CATALOG_DB

logger = logging.getLogger(__name__)

_PREFACE_PROMPT = """Write a translator's preface (5 short paragraphs) for an English translation of a classical Chinese novel. Use a warm, scholarly but accessible tone — like a sinologist writing for an educated general reader.

Work details:
- Title (English): {title_en}
- Title (Chinese): {title_zh}
- Author: {author_en} ({author_zh})
- Genre: {genre}
- Chapters in this volume: {chapter_count}
- Volume info: {volume_info}

Structure:
1. Introduce the work — its place in the Chinese literary tradition, when it was written, why it matters. Be specific to THIS work, not generic.
2. Note that this is an AI-assisted translation. Be honest about the method: "In full disclosure, this translation was assisted by AI. Without that assistance, a work of this scale and specificity would simply not be economically realistic to produce." Express hope that bringing it to a wider audience outweighs imperfections.
3. Explain the footnoting approach — cultural footnotes for Western readers, Chinese honorifics preserved as pinyin, martial/historical/institutional terminology explained on first use.
4. If multi-volume, note what this volume covers. Mention any scholarly editions that informed the work if relevant.
5. Close with a hope that the reader will be drawn to explore further.

Return ONLY the 5 paragraphs, separated by blank lines. No headings, no labels. Use {author_en} where the author name appears."""

_PREFACE_FALLBACK = [
    "This translation brings to English readers a work from the rich tradition of"
    " classical Chinese fiction. Written by {author}, it represents a genre and"
    " sensibility that remains largely inaccessible to the English-speaking world.",

    "In full disclosure, this translation was assisted by AI. Without that"
    " assistance, a work of this scale and specificity would simply not be"
    " economically realistic to produce. I hope the benefit of bringing it to a"
    " wider audience outweighs the imperfections that inevitably follow from the"
    " method.",

    "The text has been reviewed, corrected, and annotated with care. Cultural"
    " footnotes aim to give the Western reader the context that a Chinese reader"
    " would bring to the page \u2014 the history, the social conventions, the"
    " martial traditions. Chinese honorifics are preserved as pinyin (each"
    " footnoted on first use) because the social architecture of the original"
    " \u2014 who defers to whom, and how \u2014 is half the story.",

    "If the reader finishes this text with a desire to know more \u2014 to seek"
    " out the original, to explore the tradition, to argue with my footnotes"
    " \u2014 then it has served its purpose.",
]


class EpubBuilder:
    """
    EPUB3 builder with popup footnotes and content-type formatting.

    Kindle tap-to-view popup footnotes use:
        <a epub:type="noteref" href="#fn-ch3-7">[7]</a>
        ...
        <aside epub:type="footnote" id="fn-ch3-7">
          <p><strong>ideogram</strong> (pinyin) -- explanation</p>
        </aside>
    """

    def __init__(
        self,
        css_path: Optional[Path] = None,
        catalog_db: Optional[Path] = None,
        cover_image: Optional[Path] = None,
        cover_subtitle: Optional[str] = None,
        include_source: bool = False,
        show_source: bool = False,
    ):
        self.css_path = css_path or DEFAULT_CSS_PATH
        self.catalog_db = catalog_db or DEFAULT_CATALOG_DB
        self.cover_subtitle = cover_subtitle
        self.cover_image = cover_image
        self.include_source = include_source
        self.show_source = show_source
        self._catalog_cache: Dict[str, Dict[str, Any]] = {}

    def _get_catalog(self, work_number: str) -> Dict[str, Any]:
        """Cached catalog lookup."""
        if work_number not in self._catalog_cache:
            _catalog_mod = self._import_cf_catalog()
            self._catalog_cache[work_number] = _catalog_mod.lookup_catalog(
                work_number, self.catalog_db
            )
        return self._catalog_cache[work_number]

    @staticmethod
    def _import_cf_catalog():
        """Import crimson_folio's utils.catalog, avoiding shadowing by sibling products."""
        import importlib.util
        catalog_path = Path(__file__).resolve().parent.parent / "utils" / "catalog.py"
        spec = importlib.util.spec_from_file_location("cf_catalog", catalog_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _resolve_english_meta(self, meta: Dict[str, Any]) -> tuple:
        """Return (title_en, author_en) preferring catalog, then translation meta."""
        work_number = meta.get("work_number", "unknown")
        catalog = self._get_catalog(work_number)

        catalog_title = catalog.get("title_english", "")
        catalog_author = catalog.get("author_english", "")
        trans_title = meta.get("translation", {}).get("title", "")
        trans_author = meta.get("translation", {}).get("author", "")

        title_en = catalog_title or trans_title or meta.get("title", "Untitled")
        author_en = catalog_author or trans_author or meta.get("author", "Unknown")

        edition = catalog.get("edition", "")
        if edition and title_en.endswith(f"({edition})"):
            title_en = title_en[: -(len(edition) + 3)].rstrip()

        return title_en, author_en

    def build(
        self,
        input_path: Path,
        output_path: Optional[Path] = None,
        glossary_entries: Optional[List[Any]] = None,
    ) -> Path:
        """
        Build EPUB from translated JSON.

        Args:
            input_path: Path to translated JSON file
            output_path: Path for output .epub file. If None, generates an
                         English filename in the same directory as input_path.
            glossary_entries: Optional list of GlossaryAppendixEntry objects

        Returns:
            Path to generated EPUB file
        """
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if output_path is None:
            output_path = self._english_epub_path(data, input_path.parent)

        return self.build_from_data(data, output_path, glossary_entries)

    def build_from_data(
        self,
        data: Dict[str, Any],
        output_path: Path,
        glossary_entries: Optional[List[Any]] = None,
    ) -> Path:
        """
        Build EPUB from in-memory data dict.

        Args:
            data: Translated JSON data
            output_path: Path for output .epub file
            glossary_entries: Optional glossary entries

        Returns:
            Path to generated EPUB file
        """
        meta = data.get("meta", {})
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        work_number = meta.get("work_number", "unknown")

        title_en, author_en = self._resolve_english_meta(meta)
        title_zh = meta.get("title", "")
        author_zh = meta.get("author", "")

        # Look up series info from catalog
        lookup_series = EpubBuilder._import_cf_catalog().lookup_series
        series_info = lookup_series(work_number, self.catalog_db)
        series_name = series_info.get("name", "")
        series_order = series_info.get("order")
        series_total = series_info.get("total", 0)

        # Build full EPUB title: "Title (Series #1)"
        epub_title = title_en
        if series_name and series_order is not None:
            epub_title = f"{title_en} ({series_name} #{series_order})"

        # Create EPUB book
        book = epub.EpubBook()
        book.set_identifier(f"wuxia-{work_number}")
        book.set_title(epub_title)
        book.set_language("en")
        book.add_author(author_en)

        # Add cover image — compose with title overlay if raw artwork
        if self.cover_image and self.cover_image.exists():
            try:
                from covers.composer import CoverComposer
                composer = CoverComposer(width=1600, height=2560)
                composed_path = self.cover_image.parent / f"{self.cover_image.stem}_composed.jpg"

                # Build subtitle
                if self.cover_subtitle:
                    cover_sub = self.cover_subtitle
                else:
                    subtitle_parts = ["A Classic Chinese Novel in a New Translation"]
                    volume = meta.get("volume", "")
                    if volume:
                        vol_num = int(volume) if str(volume).isdigit() else volume
                        subtitle_parts.append(f"Volume {self._volume_word(vol_num)}")
                    elif series_total and series_total > 1 and series_order:
                        subtitle_parts.append(f"Volume {self._volume_word(series_order)}")
                    cover_sub = "\n".join(subtitle_parts)

                composer.compose(
                    artwork_path=self.cover_image,
                    title_en=title_en,
                    title_zh=title_zh,
                    subtitle=cover_sub,
                    author_en=author_en,
                    author_zh=author_zh,
                    output_path=composed_path,
                )
                cover_data = composed_path.read_bytes()
                # Save standalone copy next to EPUB for testing/KDP
                standalone = output_path.parent / "cover_front.jpg"
                import shutil
                shutil.copy2(composed_path, standalone)
                logger.info(f"  Composed cover → {standalone}")
            except Exception as e:
                logger.debug(f"  Cover composition failed ({e}), using raw image")
                cover_data = self.cover_image.read_bytes()
            book.set_cover("cover.jpg", cover_data, create_page=True)

        # Add publisher logo
        logo_path = Path(__file__).parent.parent / "assets" / "iron_abacus_core_logo_gray.png"
        if logo_path.exists():
            from PIL import Image as PILImage
            # Resize to small EPUB size (200px wide)
            with PILImage.open(logo_path) as logo_img:
                ratio = 200 / logo_img.width
                new_w = int(logo_img.width * ratio)
                new_h = int(logo_img.height * ratio)
                logo_resized = logo_img.resize((new_w, new_h), PILImage.LANCZOS)
                import io
                buf = io.BytesIO()
                logo_resized.save(buf, format="PNG")
                logo_data = buf.getvalue()
            logo_item = epub.EpubItem(
                uid="logo",
                file_name="images/iron_abacus_logo.png",
                media_type="image/png",
                content=logo_data,
            )
            book.add_item(logo_item)
        else:
            logo_item = None

        # Add CSS
        css_content = self._load_css()
        css_item = epub.EpubItem(
            uid="style",
            file_name="styles/kindle.css",
            media_type="text/css",
            content=css_content.encode("utf-8"),
        )
        book.add_item(css_item)

        # Build title page
        title_page = self._build_title_page(
            title_en, title_zh, author_en, author_zh, css_item=css_item,
            series_name=series_name, series_order=series_order, series_total=series_total,
            volume=meta.get("volume", ""), total_volumes=meta.get("total_volumes"),
        )
        book.add_item(title_page)

        # Build translator's preface
        # Add chapter count to meta for preface generation
        meta["_chapter_count"] = len(chapters)
        preface_page = self._build_preface(author_en, css_item, meta=meta)
        book.add_item(preface_page)

        # Build introduction
        intro_page = self._build_introduction(css_item, meta=meta)
        book.add_item(intro_page)

        # Build chapters
        chapter_items = []
        spine = ["nav", title_page, preface_page, intro_page]

        for ch_idx, chapter in enumerate(chapters):
            ch_num = ch_idx + 1
            ch_item = self._build_chapter(chapter, ch_num, css_item)
            book.add_item(ch_item)
            chapter_items.append(ch_item)
            spine.append(ch_item)

        # Build credits/colophon page
        credits_page = self._build_credits(css_item)
        book.add_item(credits_page)
        spine.append(credits_page)

        # Auto-generate acupoint glossary from footnotes + DuckDB
        acupoint_item = self._build_acupoint_glossary(data, css_item)
        if acupoint_item:
            book.add_item(acupoint_item)
            spine.append(acupoint_item)

        # Build glossary if entries provided
        glossary_item = None
        if glossary_entries:
            glossary_item = self._build_glossary(glossary_entries, css_item)
            book.add_item(glossary_item)
            spine.append(glossary_item)

        # Build TOC
        # Front matter (not numbered)
        front_matter_links = [
            epub.Link(title_page.file_name, "Title Page", "title"),
            epub.Link(preface_page.file_name, "Translator\u2019s Preface", "preface"),
            epub.Link(intro_page.file_name, "Introduction", "introduction"),
        ]

        # Chapter entries
        chapter_links = []
        for ch_idx, ch_item in enumerate(chapter_items):
            ch = chapters[ch_idx]
            ch_title = (ch.get("title_english")
                        or ch.get("translated_title")
                        or ch.get("title", ""))
            ch_title_zh = ch.get("title_chinese", "")
            if not ch_title or ch_title == ch_title_zh:
                ch_title = self._translate_chapter_title(
                    ch_title_zh or ch.get("title", ""), ch_idx + 1
                )
            ch_title_clean = re.sub(r'\[\d+\]', '', ch_title).strip().replace("*", "")

            # Reformat for TOC: "1. Title" instead of "Chapter One: Title"
            # Strip "Chapter N:" or "Chapter Word:" prefix
            toc_title = re.sub(
                r'^Chapter\s+(?:One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten'
                r'|Eleven|Twelve|Thirteen|Fourteen|Fifteen|Sixteen|Seventeen'
                r'|Eighteen|Nineteen|Twenty|\d+)\s*[:\.\-—]\s*',
                '', ch_title_clean, flags=re.IGNORECASE
            )
            if toc_title == ch_title_clean:
                # Didn't match — try Chinese format
                toc_title = re.sub(r'^第[一二三四五六七八九十百零○廿卅]+[回章]\s*', '', toc_title)

            # Truncate if still too long
            if len(toc_title) > 50:
                for sep in ['；', ';', '—', '，', ',']:
                    pos = toc_title.find(sep)
                    if 15 < pos < 50:
                        toc_title = toc_title[:pos].rstrip()
                        break
                else:
                    toc_title = toc_title[:47].rstrip() + "…"

            # Just the title — the TOC list handles numbering
            toc_entry = toc_title if toc_title else f"Chapter {ch_idx + 1}"

            chapter_links.append(
                epub.Link(ch_item.file_name, toc_entry, ch_item.id)
            )

        # Back matter
        back_matter_links = []
        if glossary_item:
            back_matter_links.append(
                epub.Link(glossary_item.file_name, "Glossary of Terms", "glossary")
            )
        back_matter_links.append(
            epub.Link(credits_page.file_name, "Credits", "credits")
        )

        # Combine TOC — front matter as flat links, chapters as section
        book.toc = front_matter_links + chapter_links + back_matter_links

        # Add navigation files
        book.add_item(epub.EpubNcx())

        # Build custom nav page with inline styling
        nav_items = []
        for link in front_matter_links:
            nav_items.append(
                f'        <li style="list-style: none; margin-bottom: 0.5em;">'
                f'<a href="{link.href}" style="color: #333; text-decoration: none; '
                f'font-style: italic; font-size: 0.9em;">{_escape(link.title)}</a></li>'
            )
        for link in chapter_links:
            nav_items.append(
                f'        <li style="list-style: none; margin-bottom: 0.6em;">'
                f'<a href="{link.href}" style="color: #222; text-decoration: none; '
                f'font-size: 0.95em;">{_escape(link.title)}</a></li>'
            )
        for link in back_matter_links:
            nav_items.append(
                f'        <li style="list-style: none; margin-bottom: 0.5em;">'
                f'<a href="{link.href}" style="color: #333; text-decoration: none; '
                f'font-style: italic; font-size: 0.9em;">{_escape(link.title)}</a></li>'
            )

        nav_html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Contents</title></head>
<body style="font-family: Georgia, 'Palatino Linotype', Palatino, serif;">
  <nav epub:type="toc" id="toc" role="doc-toc">
    <h2 style="text-align: center; font-size: 1.6em; font-weight: normal; letter-spacing: 0.1em; margin-bottom: 1.5em; padding-bottom: 0.5em; border-bottom: 1px solid #ccc;">Contents</h2>
    <ol style="list-style: none; padding-left: 0; margin: 0 1em;">
{chr(10).join(nav_items)}
    </ol>
  </nav>
</body>
</html>"""

        nav = epub.EpubNav()
        nav.set_content(nav_html.encode("utf-8"))
        nav.add_item(css_item)
        book.add_item(nav)

        # Set spine
        book.spine = spine

        # Write EPUB
        output_path.parent.mkdir(parents=True, exist_ok=True)
        epub.write_epub(str(output_path), book, {"epub3_pages": False})

        # Post-process: replace nav.xhtml with custom styled version
        # (ebooklib strips our inline styles during generation)
        self._patch_nav(output_path, front_matter_links, chapter_links, back_matter_links)

        logger.info(f"Generated EPUB: {output_path}")
        return output_path

    @staticmethod
    def _patch_nav(epub_path: Path, front_links, chapter_links, back_links):
        """Replace ebooklib's auto-generated nav with custom styled version."""
        import zipfile

        with zipfile.ZipFile(str(epub_path), 'r') as zin:
            contents = {name: zin.read(name) for name in zin.namelist()}

        # Find the nav file path (usually EPUB/nav.xhtml)
        nav_key = next((k for k in contents if k.endswith('nav.xhtml')), None)
        if not nav_key:
            return

        # Build custom nav
        items = []
        for link in front_links:
            href = link.href
            items.append(
                f'      <li style="margin-bottom: 0.5em; list-style: none;">'
                f'<a href="{href}" style="color: #555; text-decoration: none; '
                f'font-style: italic; font-size: 0.9em;">{_escape(link.title)}</a></li>'
            )

        if chapter_links:
            items.append(
                '      <li style="margin-top: 1.5em; list-style: none;">'
                '<span style="font-size: 0.85em; letter-spacing: 0.1em; '
                'color: #888; text-transform: uppercase;">Chapters</span></li>'
            )
            items.append(
                '      <li style="border-top: 1px solid #ddd; margin-bottom: 0.6em; '
                'list-style: none;"></li>'
            )
            for i, link in enumerate(chapter_links, 1):
                href = link.href
                items.append(
                    f'      <li style="margin-bottom: 0.7em; list-style: none;">'
                    f'<a href="{href}" style="color: #222; text-decoration: none;">'
                    f'{i}. {_escape(link.title)}</a></li>'
                )

        if back_links:
            items.append(
                '      <li style="margin-top: 1em; border-top: 1px solid #eee; '
                'padding-top: 0.8em; list-style: none;"></li>'
            )
            for link in back_links:
                href = link.href
                items.append(
                    f'      <li style="margin-bottom: 0.5em; list-style: none;">'
                    f'<a href="{href}" style="color: #555; text-decoration: none; '
                    f'font-style: italic; font-size: 0.9em;">{_escape(link.title)}</a></li>'
                )

        nav_html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Contents</title></head>
<body style="font-family: Georgia, 'Palatino Linotype', Palatino, serif; margin: 1em 1.5em;">
  <nav epub:type="toc" id="id" role="doc-toc">
    <h2 style="text-align: center; font-size: 1.6em; font-weight: normal; letter-spacing: 0.1em; margin-bottom: 1.5em; padding-bottom: 0.5em; border-bottom: 1px solid #ccc;">Contents</h2>
    <ol style="list-style: none; padding-left: 0; margin: 0;">
{chr(10).join(items)}
    </ol>
  </nav>
</body>
</html>"""

        contents[nav_key] = nav_html.encode('utf-8')
        # Remove orphan nav at root if exists
        if 'nav.xhtml' in contents and nav_key != 'nav.xhtml':
            del contents['nav.xhtml']

        with zipfile.ZipFile(str(epub_path), 'w', zipfile.ZIP_DEFLATED) as zout:
            for name, data in contents.items():
                zout.writestr(name, data)

    # Chinese numeral → int mapping for chapter title translation
    _CHINESE_NUMS = {
        "\u3007": 0, "\u96f6": 0, "\u4e00": 1, "\u4e8c": 2, "\u4e09": 3,
        "\u56db": 4, "\u4e94": 5, "\u516d": 6, "\u4e03": 7, "\u516b": 8,
        "\u4e5d": 9, "\u5341": 10, "\u767e": 100, "\u5343": 1000,
        "\u5eff": 20, "\u5345": 30, "\u534c": 40,
    }

    def _parse_chinese_num(self, s: str) -> Optional[int]:
        """Parse a Chinese numeral string like 十七 → 17, 卅二 → 32."""
        nums = self._CHINESE_NUMS
        if not s:
            return None
        if len(s) == 1 and s in nums:
            return nums[s]
        total = 0
        current = 0
        for ch in s:
            if ch not in nums:
                return None
            val = nums[ch]
            if val == 10:
                current = (current or 1) * 10
            elif val in (20, 30, 40):
                current += val
            elif val == 100:
                current = (current or 1) * 100
            elif val == 1000:
                current = (current or 1) * 1000
            else:
                if current >= 10:
                    current += val
                else:
                    current = current * 10 + val if current else val
        total += current
        return total if total > 0 else None

    def _translate_chapter_title(self, zh_title: str, chapter_num: int) -> str:
        """Translate Chinese chapter title to English.

        Handles patterns like:
          第一回 → Chapter 1
          第三十二章 → Chapter 32
          卷一 → Volume 1
        Falls back to "Chapter N" using the sequential number.
        """
        if not zh_title:
            return f"Chapter {chapter_num}"

        m = re.match(r"\u7b2c(.+?)(\u56de|\u7ae0|\u7bc0|\u7bc7|\u5377)", zh_title)
        if m:
            num_str = m.group(1)
            type_char = m.group(2)
            parsed = self._parse_chinese_num(num_str)
            type_map = {"\u56de": "Chapter", "\u7ae0": "Chapter", "\u7bc0": "Section",
                        "\u7bc7": "Part", "\u5377": "Volume"}
            label = type_map.get(type_char, "Chapter")
            if parsed is not None:
                suffix = zh_title[m.end():].strip()
                if suffix:
                    return f"{label} {parsed}: {suffix}"
                return f"{label} {parsed}"

        return f"Chapter {chapter_num}"

    def _english_epub_path(self, data: Dict[str, Any], output_dir: Path) -> Path:
        """Generate an English EPUB filename from metadata.

        Format: Author - Title (Series #NN).epub
        """
        meta = data.get("meta", {})
        work_number = meta.get("work_number", "unknown")
        title_en, author_en = self._resolve_english_meta(meta)

        catalog = self._get_catalog(work_number)
        lookup_series = EpubBuilder._import_cf_catalog().lookup_series
        series_info = lookup_series(work_number, self.catalog_db)
        series_suffix = ""
        if series_info.get("name") and series_info.get("order") is not None:
            total = series_info["total"]
            width = len(str(total)) if total >= 10 else 2
            series_suffix = f" ({series_info['name']} #{series_info['order']:0{width}d})"

        edition = catalog.get("edition", "")
        edition_suffix = f" [{edition}]" if edition else ""

        # Add volume marker if multi-volume work
        volume = meta.get("volume", "")
        volume_suffix = ""
        if volume:
            if volume.isdigit():
                vol_num = int(volume)
            elif len(volume) == 1 and volume.isalpha():
                vol_num = ord(volume.lower()) - ord('a') + 1  # a→1, b→2
            else:
                vol_num = volume
            volume_suffix = f" Vol. {vol_num}"

        raw_name = f"{author_en} - {title_en}{volume_suffix}{series_suffix}{edition_suffix}"
        safe_name = _sanitize_filename(raw_name)
        return output_dir / f"{safe_name}.epub"

    def _load_css(self) -> str:
        """Load CSS — from theme.json if available, otherwise static file."""
        theme_path = Path(__file__).parent.parent / "config" / "theme.json"
        if theme_path.exists():
            try:
                from styles.theme_renderer import render_css
                return render_css(theme_path)
            except Exception as e:
                logger.debug(f"Theme render failed ({e}), falling back to static CSS")
        try:
            with open(self.css_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            logger.warning(f"CSS not found at {self.css_path}, using minimal CSS")
            return "body { font-family: serif; line-height: 1.6; }"

    def _build_title_page(
        self,
        title_en: str,
        title_zh: str,
        author_en: str,
        author_zh: str,
        css_item: epub.EpubItem = None,
        series_name: str = "",
        series_order: Optional[int] = None,
        series_total: int = 0,
        volume: str = "",
        total_volumes: Optional[int] = None,
    ) -> epub.EpubHtml:
        """Build bilingual title page with series info."""
        title_zh_line = ""
        if title_zh and title_zh != title_en:
            title_zh_line = (
                f'    <p style="font-size: 1.8em; margin-bottom: 1em; color: #333; '
                f'letter-spacing: 0.2em;">{_escape(title_zh)}</p>'
            )
        author_zh_line = ""
        if author_zh and author_zh != author_en:
            author_zh_line = (
                f'    <p style="font-size: 1.05em; color: #555; margin-top: 0.3em;">'
                f'{_escape(author_zh)}</p>'
            )

        series_line = ""
        if series_name and series_order is not None:
            series_desc = f'{_escape(series_name)} &mdash; Book {series_order} of {series_total}'
            # Add volume info if this is a multi-volume work
            if volume:
                if str(volume).isdigit():
                    vol_num = int(volume)
                elif len(str(volume)) == 1 and str(volume).isalpha():
                    vol_num = ord(str(volume).lower()) - ord('a') + 1
                else:
                    vol_num = volume
                if total_volumes:
                    series_desc += f' &middot; Volume {vol_num} of {total_volumes}'
                else:
                    series_desc += f' &middot; Volume {vol_num}'
            series_line = (
                f'    <p style="font-size: 0.95em; font-style: italic; color: #555; '
                f'margin-bottom: 0.3em; letter-spacing: 0.05em;">{series_desc}</p>'
            )

        html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>{_escape(title_en)}</title>
  <link rel="stylesheet" type="text/css" href="styles/kindle.css"/>
</head>
<body>
  <div style="text-align: center; margin-top: 20%; padding: 0 1em; font-family: Georgia, 'Palatino Linotype', Palatino, serif;">
    <h1 style="font-size: 2.4em; font-weight: bold; letter-spacing: 0.03em; line-height: 1.25; margin-bottom: 0.3em; text-align: center;">{_escape(title_en)}</h1>
{title_zh_line}
{series_line}
    <p style="font-size: 1em; margin-top: 1.5em; letter-spacing: 0.05em; color: #555; font-style: italic;">A Classic Chinese Novel in a New Translation</p>
    <p style="font-size: 1.15em; margin-top: 2em; letter-spacing: 0.1em; font-weight: bold;">{_escape(author_en)}</p>
{author_zh_line}
    <p style="margin-top: 6em; text-align: center;">
      <img src="images/iron_abacus_logo.png" alt="Iron Abacus" style="width: 80px; height: auto;"/>
    </p>
  </div>
</body>
</html>"""

        item = epub.EpubHtml(
            title="Title Page",
            file_name="title.xhtml",
            lang="en",
        )
        item.set_content(html.encode("utf-8"))
        item.add_item(css_item)
        return item

    def _build_preface(
        self,
        author_en: str,
        css_item: epub.EpubItem,
        build_date: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> epub.EpubHtml:
        """Build Translator's Preface page, generated per-work via LLM or fallback."""
        if build_date is None:
            build_date = date.today().strftime("%B %Y")

        paragraphs = self._generate_preface_paragraphs(author_en, meta or {})

        body_parts = []
        for i, para in enumerate(paragraphs):
            text = para.format(author=author_en)
            # Convert markdown italics to HTML before escaping
            text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)
            text = _escape(text)
            # Restore <em> tags that _escape may have mangled
            text = text.replace("&lt;em&gt;", "<em>").replace("&lt;/em&gt;", "</em>")
            css_class = ' class="first"' if i == 0 else ""
            body_parts.append(f"    <p{css_class}>{text}</p>")

        body_parts.append('    <p class="signature">Iron Abacus</p>')
        body_parts.append(
            f'    <p class="dateline">Brooklyn, New York &mdash; {_escape(build_date)}</p>'
        )

        body_html = "\n".join(body_parts)
        html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>Translator's Preface</title>
  <link rel="stylesheet" type="text/css" href="styles/kindle.css"/>
</head>
<body>
  <div class="translators-preface">
    <h2>Translator&rsquo;s Preface</h2>
{body_html}
  </div>
</body>
</html>"""

        item = epub.EpubHtml(
            title="Translator\u2019s Preface",
            file_name="preface.xhtml",
            lang="en",
        )
        item.set_content(html.encode("utf-8"))
        item.add_item(css_item)
        return item

    def _generate_preface_paragraphs(
        self, author_en: str, meta: Dict[str, Any]
    ) -> List[str]:
        """Generate per-work preface via DeepSeek, falling back to template."""
        title_en = meta.get("title_english", "")
        title_zh = meta.get("title_chinese") or meta.get("title", "")
        author_zh = meta.get("author_chinese") or meta.get("author", "")
        genre = meta.get("category_english", "classical Chinese fiction")
        chapters = meta.get("_chapter_count", "")
        volume = meta.get("volume", "")
        total_vols = meta.get("total_volumes")

        volume_info = "single volume"
        if volume and total_vols:
            vol_num = ord(volume.lower()) - ord('a') + 1 if len(str(volume)) == 1 and str(volume).isalpha() else volume
            volume_info = f"Volume {vol_num} of {total_vols}"

        if not title_en:
            return [p for p in _PREFACE_FALLBACK]

        # Fetch Wikipedia context for factual grounding
        wiki_context = self._fetch_preface_context(title_en, title_zh, author_en, author_zh)

        try:
            from utils.llm_client import get_deepseek_client
            client = get_deepseek_client()

            prompt = _PREFACE_PROMPT.format(
                title_en=title_en, title_zh=title_zh,
                author_en=author_en, author_zh=author_zh,
                genre=genre, chapter_count=chapters or "unknown",
                volume_info=volume_info,
            )

            if wiki_context:
                prompt += (
                    "\n\nFACTUAL CONTEXT (from Wikipedia — use these facts, "
                    "do not invent dates, publication history, or claims not "
                    "supported here):\n\n" + wiki_context
                )

            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=1500,
            )
            text = response.choices[0].message.content.strip()
            paras = [p.strip() for p in text.split("\n\n") if p.strip()]
            if len(paras) >= 3:
                return paras
        except Exception as e:
            logger.debug(f"Preface generation failed, using fallback: {e}")

        return [p for p in _PREFACE_FALLBACK]

    @staticmethod
    def _fetch_preface_context(
        title_en: str, title_zh: str, author_en: str, author_zh: str
    ) -> str:
        """Fetch Wikipedia summaries for the work and author to ground the preface."""
        import httpx

        WIKI_API = "https://en.wikipedia.org/w/api.php"
        headers = {
            "User-Agent": "IronAbacusTranslator/1.0 (bot-traffic@wikimedia.org)",
        }

        def _fetch(query: str, max_chars: int = 800) -> Optional[str]:
            """Search Wikipedia and return the intro extract."""
            try:
                # Try exact title
                resp = httpx.get(WIKI_API, params={
                    "action": "query", "titles": query,
                    "prop": "extracts", "exintro": "true",
                    "explaintext": "true", "format": "json",
                }, headers=headers, timeout=15)
                pages = resp.json().get("query", {}).get("pages", {})
                for pid, page in pages.items():
                    if pid != "-1" and page.get("extract"):
                        extract = page["extract"]
                        if len(extract) > max_chars:
                            cut = extract[:max_chars]
                            last = cut.rfind(". ")
                            extract = cut[:last + 1] if last > max_chars // 3 else cut + "..."
                        return extract.strip()

                # Fallback: search API
                resp = httpx.get(WIKI_API, params={
                    "action": "query", "list": "search",
                    "srsearch": query, "srlimit": 1, "format": "json",
                }, headers=headers, timeout=15)
                results = resp.json().get("query", {}).get("search", [])
                if results:
                    found = results[0]["title"]
                    resp = httpx.get(WIKI_API, params={
                        "action": "query", "titles": found,
                        "prop": "extracts", "exintro": "true",
                        "explaintext": "true", "format": "json",
                    }, headers=headers, timeout=15)
                    pages = resp.json().get("query", {}).get("pages", {})
                    for pid, page in pages.items():
                        if pid != "-1" and page.get("extract"):
                            extract = page["extract"]
                            if len(extract) > max_chars:
                                cut = extract[:max_chars]
                                last = cut.rfind(". ")
                                extract = cut[:last + 1] if last > max_chars // 3 else cut + "..."
                            return extract.strip()
            except Exception:
                pass
            return None

        parts = []

        # Search for the work
        for query in [title_en, title_zh, f"{title_en} novel", f"{title_zh} novel"]:
            result = _fetch(query)
            if result and len(result) > 100:
                parts.append(f"ABOUT THE WORK:\n{result}")
                break

        # Search for the author
        for query in [author_en, author_zh, f"{author_en} author", f"{author_en} novelist"]:
            result = _fetch(query)
            if result and len(result) > 100:
                parts.append(f"ABOUT THE AUTHOR:\n{result}")
                break

        return "\n\n".join(parts)

    @staticmethod
    def _volume_word(num) -> str:
        """Convert volume number to English word: 1→One, 2→Two, etc."""
        words = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
                 6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten"}
        try:
            return words.get(int(num), str(num))
        except (ValueError, TypeError):
            return str(num)

    def _build_credits(self, css_item: epub.EpubItem) -> epub.EpubHtml:
        """Build credits/colophon page with image attributions."""
        html = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>Credits</title>
  <link rel="stylesheet" type="text/css" href="styles/kindle.css"/>
</head>
<body>
  <div style="text-align: center; margin-top: 15%; font-family: Georgia, serif;">
    <h2 style="font-size: 1.4em; font-weight: normal; letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 2em; padding-bottom: 0.5em; border-bottom: 1px solid #ccc;">Credits</h2>

    <p style="font-weight: bold; margin-top: 2em; margin-bottom: 0.3em; font-size: 1em;">Cover Image</p>
    <p style="text-indent: 0; margin-bottom: 0.2em;"><em>Portrait of Bao Zheng (998\u20131061)</em></p>
    <p style="text-indent: 0; margin-bottom: 0.2em;">Anonymous artist, Ming dynasty (1368\u20131644)</p>
    <p style="text-indent: 0; margin-bottom: 0.2em;">Ink and color on silk, 164.7 \u00d7 97.9 cm</p>
    <p style="text-indent: 0; margin-bottom: 0.2em;">Freer Gallery of Art, Smithsonian Institution (F1919.181)</p>
    <p style="text-indent: 0; margin-bottom: 0.2em; color: #666;">Public domain (CC0)</p>

    <p style="font-weight: bold; margin-top: 2em; margin-bottom: 0.3em; font-size: 1em;">Publisher</p>
    <p style="text-indent: 0; margin-bottom: 0.2em;">Iron Abacus</p>
    <p style="text-indent: 0; margin-bottom: 0.2em; color: #666;">Brooklyn, New York</p>

    <p style="font-weight: bold; margin-top: 2em; margin-bottom: 0.3em; font-size: 1em;">Translation</p>
    <p style="text-indent: 0; margin-bottom: 0.2em; font-size: 0.9em; color: #555;">Translated with AI assistance</p>
  </div>
</body>
</html>"""

        item = epub.EpubHtml(
            title="Credits",
            file_name="credits.xhtml",
            lang="en",
        )
        item.set_content(html.encode("utf-8"))
        item.add_item(css_item)
        return item

    def _build_introduction(self, css_item: epub.EpubItem,
                             meta: Optional[Dict[str, Any]] = None) -> epub.EpubHtml:
        """Build an Introduction page with cultural and historical context."""
        paras = self._generate_introduction(meta or {})
        body_parts = []
        for para in paras:
            # Convert markdown to HTML
            para = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', para)
            para = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', para)
            if para.startswith("<h"):
                body_parts.append(f"    {para}")
            else:
                text = _escape(para)
                text = text.replace("&lt;em&gt;", "<em>").replace("&lt;/em&gt;", "</em>")
                text = text.replace("&lt;strong&gt;", "<strong>").replace("&lt;/strong&gt;", "</strong>")
                body_parts.append(f"    <p>{text}</p>")

        body_html = "\n".join(body_parts)
        html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>Introduction</title>
  <link rel="stylesheet" type="text/css" href="styles/kindle.css"/>
</head>
<body>
  <div class="translators-preface">
    <h2>Introduction</h2>
{body_html}
  </div>
</body>
</html>"""

        item = epub.EpubHtml(
            title="Introduction",
            file_name="introduction.xhtml",
            lang="en",
        )
        item.set_content(html.encode("utf-8"))
        item.add_item(css_item)
        return item

    def _generate_introduction(self, meta: Dict[str, Any]) -> List[str]:
        """Generate per-work introduction via DeepSeek, grounded in Wikipedia facts."""
        title_en = meta.get("title_english", "")
        title_zh = meta.get("title_chinese") or meta.get("title", "")
        author_en = meta.get("author_english", "")
        author_zh = meta.get("author_chinese") or meta.get("author", "")
        genre = meta.get("category_english", "")

        if not title_en and not title_zh:
            return ["<h3>About This Work</h3>",
                    "This translation presents a work from the classical Chinese literary tradition."]

        wiki_context = self._fetch_preface_context(title_en, title_zh, author_en, author_zh)

        prompt = f"""Write an introduction (6-8 paragraphs) for an English translation of a classical Chinese novel. This is for a reader who knows nothing about the work or its tradition.

Work: {title_en} ({title_zh}) by {author_en} ({author_zh})
Genre: {genre or 'classical Chinese fiction'}

Structure with these section headings (use <h3> tags):

<h3>The Author</h3>
Brief biography — when they lived, their literary significance, other notable works.

<h3>The Genre</h3>
Explain the genre tradition this work belongs to. What makes it distinctive? How does it relate to other Chinese literary traditions?

<h3>The Novel</h3>
What is this specific work about (without spoilers beyond chapter 1-2)? What themes does it explore? What should the reader expect in terms of narrative style?

Rules:
- Use ONLY facts from the Wikipedia context below. Do NOT invent biographical details, dates, or claims.
- If Wikipedia doesn't cover something, say "little is known" rather than fabricating.
- Write for an educated general reader, not a specialist.
- Use *italics* for Chinese terms and titles.
- Keep each paragraph 3-5 sentences.

{('FACTUAL CONTEXT:\\n' + wiki_context) if wiki_context else 'No Wikipedia context available — keep to well-known facts only.'}

Return paragraphs separated by blank lines. Include the <h3> section headings."""

        try:
            from utils.llm_client import get_deepseek_client
            client = get_deepseek_client()
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=3000,
            )
            text = response.choices[0].message.content.strip()
            # Split on blank lines, then further split <h3> tags onto their own lines
            raw_paras = [p.strip() for p in text.split("\n\n") if p.strip()]
            paras = []
            for p in raw_paras:
                # If paragraph contains <h3>, split it out
                if "<h3>" in p:
                    parts = re.split(r'(<h3>.*?</h3>)', p)
                    for part in parts:
                        part = part.strip()
                        if part:
                            paras.append(part)
                else:
                    paras.append(p)
            if len(paras) >= 4:
                return paras
        except Exception as e:
            logger.debug(f"Introduction generation failed: {e}")

        return ["<h3>About This Work</h3>",
                f"*{title_en}* ({title_zh}) by {author_en} is a work from the classical Chinese literary tradition.",
                "This translation aims to bring this work to English-language readers for the first time."]

    def _build_introduction_legacy(self, css_item: epub.EpubItem) -> epub.EpubHtml:
        """LEGACY: Hardcoded introduction for 三俠五義. Kept for reference."""
        paras = [
            "<h3>The Author</h3>",
            "Sh\u00ed Y\u00f9k\u016bn (\u77f3\u7389\u5d11, fl. 19th century)"
            " was not a writer in the conventional sense. He was a"
            " <em>p\u00edngsh\u016b</em> performer \u2014 a professional oral"
            " storyteller who performed in Beijing during the first half of the"
            " nineteenth century. Little is known of his life; anecdotes recorded"
            " decades later suggest he worked in the household of a Manchu prince"
            " before becoming a performer. His art form involved a single"
            " storyteller narrating extended tales over many sessions, using"
            " nothing but a folding fan and a wooden block, with the audience"
            " returning night after night. The Three Heroes and Five Gallants"
            " was Sh\u00ed Y\u00f9k\u016bn\u2019s masterwork, transcribed from"
            " his performances and first published in 1879.",

            # THE GENRE
            "<h3>The G\u014dng\u2019\u00e0n Tradition</h3>",
            "G\u014dng\u2019\u00e0n (\u516c\u6848, \u201ccourt-case\u201d)"
            " fiction is one of the oldest narrative genres in China. Its roots"
            " lie in the colloquial stories of the Song dynasty, and it"
            " developed into one of the most popular genres of the Ming and"
            " Q\u012bng dynasties."
            " The most famous of these was B\u0101o Zh\u011bng, known to posterity"
            " as Judge B\u0101o or B\u0101o Q\u012bngti\u0101n (\u201cB\u0101o"
            " Blue-Sky\u201d) \u2014 a title reflecting his reputation for"
            " unclouded justice.",

            "Where European detective fiction begins with a mystery and works"
            " toward a solution, g\u014dng\u2019\u00e0n fiction begins with"
            " injustice and works toward redress. The magistrate is not a"
            " private investigator but a representative of cosmic order. His"
            " courtroom is a stage where heaven\u2019s justice is enacted on"
            " earth. This gives the genre a moral weight quite unlike the"
            " puzzle-box tradition of Western detective fiction.",

            # WHAT MAKES THIS NOVEL DISTINCTIVE
            "<h3>The Novel</h3>",
            "Sh\u00ed Y\u00f9k\u016bn\u2019s great innovation was to fuse"
            " the g\u014dng\u2019\u00e0n magistrate tradition with"
            " w\u01d4xi\u00e1 \u2014 the chivalric martial-arts tradition."
            " His Judge B\u0101o does not act alone. He is supported by a"
            " cast of jianghu outlaws, wandering swordsmen, and reformed"
            " bandits: the \u201cthree heroes\u201d and \u201cfive gallants\u201d"
            " of the title. The result is a novel of extraordinary range,"
            " moving between the imperial court, the magistrate\u2019s"
            " tribunal, the jianghu underworld, and the open road.",

            "The reader will encounter several distinctive features of the"
            " oral storytelling tradition. The narrator regularly addresses"
            " the audience directly (\u201cNow it is told that\u2026\u201d,"
            " \u201cTo know what happened next, listen to the next chapter"
            "\u201d). Events are recounted with a storyteller\u2019s relish"
            " for suspense, digression, and dramatic irony. The prose shifts"
            " register constantly \u2014 from the formal language of the court"
            " to the rough slang of the jianghu, from classical verse to"
            " marketplace comedy. This is a novel meant to be heard as much"
            " as read.",

            # THE REAL BAO ZHENG
            "<h3>The Historical B\u0101o Zh\u011bng</h3>",
            "The real B\u0101o Zh\u011bng (999\u20131062) was a civil official"
            " of the Northern Song dynasty who served as Prefect of K\u0101if\u0113ng,"
            " the imperial capital, from 1057 to 1058. During his twenty-five"
            " years in civil service, he was known for his honesty and"
            " uprightness \u2014 he impeached powerful officials, including an"
            " uncle of the Emperor\u2019s favourite concubine, and initiated"
            " reforms to hear the grievances of common people directly.",

            "The legends far outstrip the history. In popular imagination,"
            " B\u0101o Zh\u011bng acquired a dark complexion (symbolising"
            " justice), a crescent-moon birthmark on his forehead, three"
            " iron guillotines for executing criminals of different rank, and"
            " the ability to judge cases in the underworld by night. Very"
            " little of this is historical. But it is the legend, not the"
            " history, that drives the novel \u2014 and the legend is"
            " magnificent.",
        ]

        body_html = "\n".join(
            f"    {p}" if p.startswith("<h") else f"    <p>{p}</p>"
            for p in paras
        )

        html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>Introduction</title>
  <link rel="stylesheet" type="text/css" href="styles/kindle.css"/>
</head>
<body>
  <div class="translators-preface">
    <h2>Introduction</h2>
{body_html}
  </div>
</body>
</html>"""

        item = epub.EpubHtml(
            title="Introduction",
            file_name="introduction.xhtml",
            lang="en",
        )
        item.set_content(html.encode("utf-8"))
        item.add_item(css_item)
        return item

    def _build_chapter(
        self,
        chapter: Dict[str, Any],
        chapter_num: int,
        css_item: epub.EpubItem,
    ) -> epub.EpubHtml:
        """Build a single chapter XHTML file with popup footnotes."""
        title_en = (chapter.get("title_english")
                    or chapter.get("translated_title")
                    or chapter.get("title", ""))
        title_zh = chapter.get("title_chinese", "")
        if not title_en or title_en == title_zh:
            title_en = self._translate_chapter_title(title_zh or chapter.get("title", ""), chapter_num)
        title_en = re.sub(r'\[\d+\]', '', title_en).strip()
        blocks = chapter.get("content_blocks", [])
        _title_zh = (chapter.get("title_chinese") or "").strip()

        body_parts = []

        # Chapter heading
        title_html = _escape(title_en)
        title_html = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', title_html)
        title_html = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', title_html)
        title_html = title_html.replace('**', '').replace('*', '')
        heading = f'<h2>{title_html}</h2>'
        body_parts.append(heading)

        chapter_footnotes: List[Dict[str, Any]] = []
        prev_content_type: Optional[str] = None

        # Pre-pass: detect couplet/inscription patterns — short blocks
        # following an intro ending with ':' get grouped as verse.
        _verse_override: set[int] = set()
        _narr_override: set[int] = set()  # document blocks to render as narrative
        for bi in range(len(blocks) - 1):
            intro = (blocks[bi].get("translated_content") or "").rstrip()
            if not intro.endswith(":"):
                continue
            ct = blocks[bi].get("content_type", "")
            if ct in ("verse", "document"):
                continue
            # Scan ahead for short, single-line, non-dialogue blocks
            found_verse = False
            for bj in range(bi + 1, min(bi + 6, len(blocks))):
                candidate = (blocks[bj].get("translated_content") or "").strip()
                ctype = blocks[bj].get("content_type", "")
                if not candidate:
                    continue
                if ctype == "document":
                    # A document block right after couplet lines is the
                    # inscription dedication — render as narrative, not
                    # blockquote.
                    if found_verse:
                        _narr_override.add(bj)
                    break
                is_short_line = (
                    len(candidate) < 150
                    and "\n" not in candidate
                    and candidate[0] not in '"\u201c'
                    and ctype not in ("dialogue", "verse")
                )
                if is_short_line:
                    _verse_override.add(bj)
                    found_verse = True
                else:
                    break

        _SEPARATOR_RE = re.compile(r'^[\s※＊\*·•◇◆○●△▲▽▼■□▪▫─━═☆★\-_=~.。]+$')

        for block_idx, block in enumerate(blocks):
            translated = block.get("translated_content", "")
            content_type = block.get("content_type", "narrative")

            # Render section separators as centered dividers with spacing
            source = block.get("content", "").strip()
            if source and _SEPARATOR_RE.match(source):
                body_parts.append(
                    '<p style="text-align:center; margin:1.5em 0; letter-spacing:0.5em; '
                    'color:#999;">* * *</p>'
                )
                prev_content_type = None
                continue
            if block_idx in _narr_override:
                content_type = "narrative"
            footnotes = block.get("footnotes", [])

            block_type = block.get("type", "")
            if block_type == "heading":
                continue
            block_title_zh = _title_zh
            block_source = (block.get("content") or "").strip()
            if block_idx <= 1 and block_title_zh and block_source == block_title_zh:
                continue

            if not translated:
                continue

            # Use footnote keys as-is (pipeline pre-renumbers chapter-continuously)
            # Build identity map for _render_text_with_noterefs
            old_to_new = {}
            block_footnotes = []
            for fn in footnotes:
                key = fn.get("key", 0)
                if f"[{key}]" not in translated:
                    continue
                old_to_new[key] = key  # identity — no remapping
                fn_entry = {
                    "key": key,
                    "epub_id": f"fn-ch{chapter_num}-{key}",
                    "ideogram": fn.get("ideogram", ""),
                    "pinyin": fn.get("pinyin", ""),
                    "explanation": fn.get("explanation", ""),
                }
                block_footnotes.append(fn_entry)
                chapter_footnotes.append(fn_entry)

            # Override content_type for detected couplet/inscription lines.
            # Group consecutive verse-override blocks into a single
            # <div class="verse"> wrapper.
            if block_idx in _verse_override:
                rendered_text = self._render_text_with_noterefs(
                    translated, old_to_new, chapter_num
                )
                # Check if we're extending an existing verse group
                if (body_parts
                        and body_parts[-1].startswith('<div class="verse">')
                        and (block_idx - 1) in _verse_override):
                    # Append line into the existing verse div
                    body_parts[-1] = (
                        body_parts[-1].removesuffix("</div>")
                        + f"<p>{rendered_text}</p></div>"
                    )
                else:
                    body_parts.append(
                        f'<div class="verse"><p>{rendered_text}</p></div>'
                    )
                prev_content_type = "verse"
                continue

            if content_type in ("verse", "document"):
                rendered_text = self._render_text_with_noterefs(
                    translated, old_to_new, chapter_num
                )
                body_parts.append(
                    self._wrap_content_type(rendered_text, content_type)
                )
                prev_content_type = content_type
                continue

            raw_segments = self._split_dialogue_segments(translated)

            _speech = {"dialogue"}
            _prose = {"narrative", "descriptive"}

            for seg_idx, raw_seg in enumerate(raw_segments):
                seg_class = content_type
                if raw_seg and raw_seg[0] in '"\u201c':
                    seg_class = "dialogue"
                elif content_type == "dialogue" and raw_seg and raw_seg[0] not in '"\u201c':
                    seg_class = "narrative"

                is_transition = (
                    prev_content_type is not None
                    and (
                        (prev_content_type in _prose and seg_class in _speech)
                        or (prev_content_type in _speech and seg_class in _prose)
                    )
                )
                prev_content_type = seg_class

                rendered_seg = self._render_text_with_noterefs(
                    raw_seg, old_to_new, chapter_num
                )
                t_style = ' style="margin-top:0.8em"' if is_transition else ""
                body_parts.append(
                    f'<p class="{seg_class}"{t_style}>{rendered_seg}</p>'
                )

            # Include original Chinese source text after the translated block
            if self.include_source:
                source = block.get("content", "").strip()
                if source:
                    if self.show_source:
                        style = ("color:#888; font-size:0.75em; line-height:1.4; "
                                 "margin-top:0.1em; margin-bottom:1em; font-family:serif;")
                    else:
                        style = "display:none;"
                    body_parts.append(
                        f'<p class="source" style="{style}">{_escape(source)}</p>'
                    )

        if chapter_footnotes:
            body_parts.append(
                self._render_chapter_footnotes(chapter_footnotes)
            )

        body_html = "\n".join(body_parts)
        html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>{_escape(title_en)}</title>
  <link rel="stylesheet" type="text/css" href="styles/kindle.css"/>
</head>
<body>
{body_html}
</body>
</html>"""

        item = epub.EpubHtml(
            title=title_en,
            file_name=f"chapter_{chapter_num:03d}.xhtml",
            lang="en",
        )
        item.set_content(html.encode("utf-8"))
        item.add_item(css_item)
        return item

    def _render_text_with_noterefs(
        self,
        text: str,
        old_to_new: Dict[int, int],
        chapter_num: int,
    ) -> str:
        """Replace [N] markers with EPUB3 noteref links."""
        def replace_marker(match):
            old_key = int(match.group(1))
            new_key = old_to_new.get(old_key)
            if new_key is None:
                return ""
            fn_id = f"fn-ch{chapter_num}-{new_key}"
            ref_id = f"fnref-ch{chapter_num}-{new_key}"
            return (
                f'<a id="{ref_id}" epub:type="noteref" '
                f'href="#{fn_id}">[{new_key}]</a>'
            )

        result = re.sub(r'\[(\d+)\]', replace_marker, _escape(text))
        result = re.sub(r'(?<!\*)\b(\w+)\*(?!\*)', r'*\1*', result)
        result = re.sub(r'(?<!\*)\*(\w+)\b(?!\*)', r'*\1*', result)
        result = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', result)

        def _italic_if_short(m):
            content = m.group(1)
            if len(content.split()) <= 3:
                return f'<em>{content}</em>'
            return content

        result = re.sub(r'\*([^*]+)\*', _italic_if_short, result)
        result = result.replace('**', '').replace('*', '')
        return result

    @staticmethod
    def _split_dialogue_segments(text: str) -> List[str]:
        """Split a block into dialogue and narrative segments.

        Each quoted speech line (with its attribution if present)
        becomes its own segment. Narrative passages between quotes
        also become separate segments.

        Handles split quotes: "start," he said, "end." stays as one unit.
        """
        if "\n\n" in text:
            return [s.strip() for s in text.split("\n\n") if s.strip()]

        Q_OPEN = '"\u201c'
        Q_CLOSE = '"\u201d'

        tokens: List[dict] = []
        i = 0
        while i < len(text):
            if text[i] in Q_OPEN:
                j = i + 1
                while j < len(text) and text[j] not in Q_CLOSE:
                    j += 1
                if j < len(text):
                    j += 1
                tokens.append({"type": "quote", "text": text[i:j], "start": i})
                i = j
            else:
                j = i
                while j < len(text) and text[j] not in Q_OPEN:
                    j += 1
                tokens.append({"type": "narr", "text": text[i:j], "start": i})
                i = j

        # Pre-pass: merge inline quoted terms into surrounding narr
        merged_tokens: List[dict] = []
        for tok in tokens:
            if (tok["type"] == "quote"
                    and merged_tokens
                    and merged_tokens[-1]["type"] == "narr"):
                inner = tok["text"].strip().strip('"\u201c\u201d')
                inner_core = inner.rstrip('.!?, ')
                prev_narr = merged_tokens[-1]["text"].rstrip()
                # If preceding narration has no sentence-terminal or
                # speech-introducing punct, the sentence is incomplete —
                # quote is always inline (e.g. "...the sobriquet" +
                # "Brocade-Furred Marten.")  Comma excluded because it
                # introduces speech (He said, "...").
                prev_incomplete = (
                    prev_narr and prev_narr[-1] not in '.!?:;,'
                )
                is_inline = (
                    prev_incomplete
                    or len(inner_core) < 10
                    or (len(inner) < 30
                        and not any(inner.rstrip().endswith(p) for p in '.!?'))
                )
                if is_inline:
                    merged_tokens[-1]["text"] += tok["text"]
                    merged_tokens[-1]["type"] = "narr"
                    continue
            if (tok["type"] == "narr"
                    and merged_tokens
                    and merged_tokens[-1]["type"] == "narr"):
                merged_tokens[-1]["text"] += tok["text"]
                continue
            merged_tokens.append(dict(tok))
        tokens = merged_tokens

        def _ends_with_comma(q_text):
            s = q_text.rstrip()
            return len(s) >= 2 and s[-2] == ','

        def _is_dialogue_tag(narr_text: str) -> bool:
            """Return True if narr_text starts with a lowercase dialogue tag.

            Matches: 'he declared.' / 'she said, turning away.'
            Must start lowercase (continuation, not a new sentence).
            """
            return bool(narr_text) and narr_text[0].islower()

        segments: List[str] = []
        idx = 0
        while idx < len(tokens):
            tok = tokens[idx]

            if tok["type"] == "quote":
                merged = tok["text"]

                if _ends_with_comma(merged):
                    while (idx + 2 < len(tokens)
                           and tokens[idx + 1]["type"] == "narr"
                           and tokens[idx + 2]["type"] == "quote"):
                        narr_text = tokens[idx + 1]["text"].strip()
                        if narr_text and narr_text[-1] in '.!?':
                            break
                        next_q = tokens[idx + 2]["text"]
                        merged += tokens[idx + 1]["text"] + next_q
                        idx += 2
                        if not _ends_with_comma(next_q):
                            break

                if (_ends_with_comma(merged)
                        and idx + 1 < len(tokens)
                        and tokens[idx + 1]["type"] == "narr"):
                    narr_text = tokens[idx + 1]["text"].strip()
                    if not narr_text:
                        idx += 1
                    elif narr_text[-1] in '.!?':
                        merged += tokens[idx + 1]["text"]
                        idx += 1

                # Absorb trailing dialogue attribution after non-comma
                # endings (e.g. '...scoundrel!" he declared.')
                if (not _ends_with_comma(merged)
                        and idx + 1 < len(tokens)
                        and tokens[idx + 1]["type"] == "narr"):
                    narr_raw = tokens[idx + 1]["text"]
                    narr_text = narr_raw.strip()
                    if narr_text and _is_dialogue_tag(narr_text):
                        # Find first sentence end to split tag from rest
                        import re as _re
                        m = _re.search(r'[.!?](?:\s|$)', narr_text)
                        if m:
                            cut = m.end()
                            tag_part = narr_text[:cut]
                            rest = narr_text[cut:].strip()
                            merged += " " + tag_part
                            if rest:
                                # Put remainder back as a new narr token
                                tokens[idx + 1] = {
                                    "type": "narr",
                                    "text": rest,
                                    "start": tokens[idx + 1]["start"],
                                }
                            else:
                                idx += 1
                        else:
                            # No sentence end — absorb whole thing
                            merged += narr_raw
                            idx += 1

                segments.append(merged.strip())

            else:
                narr = tok["text"]
                if (narr.rstrip()[-1:] in ',:'
                        and idx + 1 < len(tokens)
                        and tokens[idx + 1]["type"] == "quote"):
                    narr += tokens[idx + 1]["text"]
                    idx += 1
                    if (_ends_with_comma(narr)
                            and idx + 1 < len(tokens)
                            and tokens[idx + 1]["type"] == "narr"):
                        att = tokens[idx + 1]["text"].strip()
                        if att and att[-1] in '.!?':
                            narr += tokens[idx + 1]["text"]
                            idx += 1
                t = narr.strip()
                if t:
                    segments.append(t)
            idx += 1

        return segments if len(segments) > 1 else [text]

    def _wrap_content_type(
        self, html_text: str, content_type: str, *, transition: bool = False
    ) -> str:
        """Wrap rendered text in content-type-appropriate HTML."""
        t_style = ' style="margin-top:0.8em"' if transition else ""
        if content_type == "verse":
            lines = html_text.split("\n")
            inner = "".join(f"<p>{line}</p>" for line in lines if line.strip())
            return f'<div class="verse"{t_style}>{inner}</div>'
        elif content_type == "document":
            return f'<blockquote class="document"{t_style}>{html_text}</blockquote>'
        else:
            css_class = content_type if content_type in (
                "dialogue", "narrative", "descriptive", "thought"
            ) else "narrative"
            segments = self._split_dialogue_segments(html_text)
            parts = []
            for idx, seg in enumerate(segments):
                style = t_style if idx == 0 else ""
                seg_class = css_class
                if seg and seg[0] in '"\u201c':
                    seg_class = "dialogue"
                elif css_class == "dialogue" and seg and seg[0] not in '"\u201c':
                    seg_class = "narrative"
                parts.append(f'<p class="{seg_class}"{style}>{seg}</p>')
            return "\n".join(parts)

    def _render_chapter_footnotes(
        self, footnotes: List[Dict[str, Any]]
    ) -> str:
        """Render footnotes as EPUB3 aside elements for popup support."""
        parts = []

        parts.append('<section class="chapter-footnotes">')
        parts.append('<h3>Notes</h3>')
        for fn in footnotes:
            fn_id = fn["epub_id"]
            ref_id = fn_id.replace("fn-", "fnref-")
            ideogram = _escape(fn.get("ideogram", ""))
            pinyin = _escape(fn.get("pinyin", ""))
            explanation = _md_inline(fn.get("explanation", ""))

            entry = (
                f'<a href="#{ref_id}" class="fn-number">[{fn["key"]}]</a> '
            )
            entry += f'<strong>{ideogram}</strong>'
            if pinyin:
                entry += f' ({pinyin})'
            if explanation:
                entry += f' &mdash; {explanation}'

            parts.append(
                f'<div epub:type="footnote" id="{fn_id}" '
                f'class="footnote-entry"><p>{entry}</p></div>'
            )
        parts.append('</section>')

        return "\n".join(parts)

    def _build_dramatis_personae(
        self,
        characters: List[Dict[str, Any]],
        css_item: epub.EpubItem,
    ) -> epub.EpubHtml:
        """Build Dramatis Personae back-matter page."""
        historical = [c for c in characters if c.get("dp_type") == "historical"
                      or (c.get("is_historical") and not c.get("dp_type"))]
        fictional = [c for c in characters if c.get("dp_type", "fictional") == "fictional"
                     and not c.get("is_historical")]
        groups = [c for c in characters if c.get("dp_type") == "group"]

        parts = [
            '<section class="dramatis-personae">',
            '<h2>Dramatis Personae</h2>',
        ]

        if historical:
            parts.append('<div class="dp-group">')
            parts.append('<h3>Historical Figures</h3>')
            for ch in sorted(historical, key=lambda c: c.get("first_chapter", 0)):
                parts.append(self._format_dp_entry(ch))
            parts.append('</div>')

        if fictional:
            parts.append('<div class="dp-group">')
            parts.append('<h3>Fictional Characters</h3>')
            for ch in sorted(fictional, key=lambda c: c.get("first_chapter", 0)):
                parts.append(self._format_dp_entry(ch))
            parts.append('</div>')

        if groups:
            parts.append('<div class="dp-group">')
            parts.append('<h3>Sects &amp; Factions</h3>')
            for ch in sorted(groups, key=lambda c: c.get("first_chapter", 0)):
                parts.append(self._format_dp_entry(ch))
            parts.append('</div>')

        parts.append('</section>')

        html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>Dramatis Personae</title>
  <link rel="stylesheet" type="text/css" href="styles/kindle.css"/>
</head>
<body>
{chr(10).join(parts)}
</body>
</html>"""

        item = epub.EpubHtml(
            title="Dramatis Personae",
            file_name="dramatis_personae.xhtml",
            lang="en",
        )
        item.set_content(html.encode("utf-8"))
        item.add_item(css_item)
        return item

    @staticmethod
    def _format_dp_entry(entry: Dict[str, Any]) -> str:
        """Format a single Dramatis Personae entry as HTML."""
        ideogram = _escape(entry.get("ideogram", ""))
        pinyin = _escape(entry.get("pinyin", ""))
        explanation = _md_inline(entry.get("explanation", ""))
        chapter = entry.get("first_chapter", "")

        html = '<div class="dp-entry">'
        html += f'<p><strong>{pinyin}</strong>'
        if ideogram:
            html += f' <span class="dp-ideogram">({ideogram})</span>'
        html += f' &mdash; {explanation}</p>'
        if chapter:
            html += f'<p class="dp-first-appearance">First appears: Chapter {chapter}</p>'
        html += '</div>'
        return html

    def _build_glossary(
        self,
        entries: List[Any],
        css_item: epub.EpubItem,
    ) -> epub.EpubHtml:
        """Build glossary appendix chapter."""
        from builders.glossary_renderer import group_by_category
        groups = group_by_category(entries)

        parts = ['<section class="glossary">', '<h2>Glossary of Terms</h2>']

        for category, cat_entries in groups.items():
            parts.append('<div class="glossary-category">')
            parts.append(f'<h3>{_escape(category)}</h3>')

            for entry in cat_entries:
                ideogram = _escape(entry.ideogram)
                pinyin = _escape(entry.pinyin)
                explanation = _md_inline(entry.explanation)

                parts.append('<div class="glossary-entry">')
                parts.append(
                    f'<span class="ge-term">{pinyin}</span> '
                    f'<span class="ge-ideogram">({ideogram})</span>'
                )
                parts.append(
                    f'<span class="ge-explanation">{explanation}</span>'
                )
                if entry.first_chapter:
                    parts.append(
                        f'<span class="ge-first-chapter">'
                        f'First appears: Chapter {entry.first_chapter}'
                        f'</span>'
                    )
                parts.append('</div>')

            parts.append('</div>')

        parts.append('</section>')

        html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>Glossary of Terms</title>
  <link rel="stylesheet" type="text/css" href="styles/kindle.css"/>
</head>
<body>
{chr(10).join(parts)}
</body>
</html>"""

        item = epub.EpubHtml(
            title="Glossary of Terms",
            file_name="glossary.xhtml",
            lang="en",
        )
        item.set_content(html.encode("utf-8"))
        item.add_item(css_item)
        return item


    def _build_acupoint_glossary(
        self,
        data: Dict[str, Any],
        css_item: epub.EpubItem,
    ) -> Optional[epub.EpubHtml]:
        """Build acupoint glossary appendix from footnotes cross-referenced with DuckDB.

        Scans all footnotes for acupoint references, looks up verified data
        from the acupoints table, and builds a formatted appendix.
        """
        # Collect acupoint ideograms from footnotes
        acupoint_ideograms = set()
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        for chapter in chapters:
            for block in chapter.get("content_blocks", []):
                for fn in block.get("footnotes", []):
                    expl = fn.get("explanation", "").lower()
                    if any(t in expl for t in (
                        "acupoint", "acupuncture", "pressure point",
                        "meridian point", "vital point",
                    )):
                        acupoint_ideograms.add(fn.get("ideogram", ""))

        if not acupoint_ideograms:
            return None

        # Look up from DuckDB
        try:
            import duckdb
            from pathlib import Path as _P
            glossary_db = _P(self.catalog_db).parent / "glossary.duckdb"
            conn = duckdb.connect(str(glossary_db), read_only=True)
            rows = conn.execute(
                "SELECT chinese, pinyin, code, english_name, meridian, location, "
                "martial_context "
                "FROM acupoints ORDER BY code"
            ).fetchall()
            conn.close()
        except Exception:
            return None

        if not rows:
            return None

        # Filter to acupoints that appear in this work's footnotes
        entries = []
        for chinese, pinyin, code, english, meridian, location, martial in rows:
            base = chinese.replace("穴", "")
            if any(base in ideo or ideo in chinese for ideo in acupoint_ideograms):
                entries.append({
                    "chinese": chinese, "pinyin": pinyin, "code": code or "",
                    "english": english or "", "meridian": meridian or "",
                    "location": location or "", "martial": martial or "",
                })

        if not entries:
            return None

        # Build HTML — list format instead of table for better Kindle rendering
        parts = [
            '<section class="acupoint-glossary">',
            '<h2 style="text-align:center; font-size:1.4em; margin-bottom:1.5em;">'
            'Glossary of Acupoints</h2>',
            '<p style="font-size:0.9em; color:#555; margin-bottom:1.5em;">'
            'The following acupuncture points appear in this volume. '
            'Codes follow WHO standard nomenclature.</p>',
            '<td style="padding:4px;">Code</td>'
            '<td style="padding:4px;">Chinese</td>'
        ]

        for e in entries:
            parts.append('<div style="margin-bottom:1.2em; border-bottom:1px solid #eee; padding-bottom:0.8em;">')
            parts.append(
                f'<p style="margin:0;"><strong><em>{_escape(e["pinyin"])}</em></strong> '
                f'{_escape(e["chinese"])} '
                f'— {_escape(e["english"])}</p>'
            )
            if e["location"]:
                parts.append(
                    f'<p style="margin:0.2em 0 0 0; font-size:0.85em; color:#555;">'
                    f'<strong>Location:</strong> {_escape(e["location"])}. '
                    f'<strong>Meridian:</strong> {_escape(e["meridian"])}.</p>'
                )
            if e["martial"]:
                parts.append(
                    f'<p style="margin:0.2em 0 0 0; font-size:0.85em; color:#555;">'
                    f'<strong>In martial arts:</strong> {_escape(e["martial"])}</p>'
                )
            parts.append('</div>')
        parts.append('</section>')

        html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>Glossary of Acupoints</title>
  <link rel="stylesheet" type="text/css" href="styles/kindle.css"/>
</head>
<body>
{chr(10).join(parts)}
</body>
</html>"""

        item = epub.EpubHtml(
            title="Glossary of Acupoints",
            file_name="acupoints.xhtml",
            lang="en",
        )
        item.set_content(html.encode("utf-8"))
        item.add_item(css_item)
        return item


def _sanitize_filename(name: str) -> str:
    """Remove or replace characters unsafe for filenames."""
    name = re.sub(r'[\\/:*?"<>|]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > 200:
        name = name[:200].rsplit(' ', 1)[0]
    return name


def _escape(text: str) -> str:
    """Escape HTML entities."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _md_inline(text: str) -> str:
    """Convert markdown inline formatting to HTML after escaping."""
    escaped = _escape(text)
    escaped = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', escaped)

    def _italic_short(m):
        content = m.group(1)
        if len(content.split()) <= 3:
            return f'<em>{content}</em>'
        return content

    escaped = re.sub(r'\*([^*]+)\*', _italic_short, escaped)
    escaped = escaped.replace('*', '')
    return escaped
