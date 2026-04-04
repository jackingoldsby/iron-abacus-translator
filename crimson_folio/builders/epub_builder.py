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

_PREFACE_PARAGRAPHS = [
    "This translation was produced using an automated workflow developed by"
    " Iron Abacus.",
    "The motivation for its development was personal. Wuxia, while culturally"
    " significant across China, Taiwan, and the broader Chinese-speaking"
    " world, is a specialized interest in the non-Chinese-speaking"
    " community \u2014 particularly in the case of novels, versus cinema and"
    " videogames, which are more accessible. Where translations existed,"
    " they were frequently abridged.",
    "Fan translators have been doing this work by hand, for love of the"
    " genre, for decades. However, lately, for better or worse, the online"
    " translation community\u2019s energy has largely gone toward xianxia"
    " and web novels.",
    "My interest has largely been in reading new school wuxia novels \u2014"
    " the historically grounded, literarily ambitious works of writers like"
    " {author} \u2014 that are unlikely to receive commercial or fan"
    " translation in the foreseeable future. Hence, over some months, I"
    " attempted to build an application that handles the full process:"
    " translation, cultural annotation, and formatting for ebook, as a"
    " single workflow.",
    "AI is a blunt instrument. It handles prose competently and cultural"
    " context tolerably; it struggles with register, poetry, and the subtler"
    " literary qualities that make these novels worth translating in the"
    " first place. Errors exist. Treat these as a working text, not a"
    " finished one.",
    "That said, I hope the reader finds some enjoyment in it despite its"
    " flaws.",
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
    ):
        self.css_path = css_path or DEFAULT_CSS_PATH
        self.catalog_db = catalog_db or DEFAULT_CATALOG_DB
        self.cover_image = cover_image
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

        # Add cover image if available
        if self.cover_image and self.cover_image.exists():
            cover_data = self.cover_image.read_bytes()
            suffix = self.cover_image.suffix.lower()
            media_type = {
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png",
            }.get(suffix, "image/jpeg")
            book.set_cover(f"cover{suffix}", cover_data)

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
            title_en, title_zh, author_en, author_zh,
            series_name=series_name, series_order=series_order, series_total=series_total,
        )
        title_page.add_item(css_item)
        book.add_item(title_page)

        # Build translator's preface
        preface_page = self._build_preface(author_en, css_item)
        book.add_item(preface_page)

        # Build chapters
        chapter_items = []
        spine = ["nav", title_page, preface_page]

        for ch_idx, chapter in enumerate(chapters):
            ch_num = ch_idx + 1
            ch_item = self._build_chapter(chapter, ch_num, css_item)
            book.add_item(ch_item)
            chapter_items.append(ch_item)
            spine.append(ch_item)

        # Build glossary if entries provided
        glossary_item = None
        if glossary_entries:
            glossary_item = self._build_glossary(glossary_entries, css_item)
            book.add_item(glossary_item)
            spine.append(glossary_item)

        # Build TOC
        toc_entries = [
            epub.Link(title_page.file_name, "Title Page", "title"),
            epub.Link(preface_page.file_name, "Translator\u2019s Preface", "preface"),
        ]
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
            toc_entries.append(
                epub.Link(ch_item.file_name, ch_title_clean, ch_item.id)
            )
        if glossary_item:
            toc_entries.append(
                epub.Link(glossary_item.file_name, "Glossary of Terms", "glossary")
            )

        book.toc = toc_entries

        # Add navigation files
        book.add_item(epub.EpubNcx())
        nav = epub.EpubNav()
        nav.add_link(href=css_item.file_name, rel="stylesheet", type="text/css")
        book.add_item(nav)

        # Set spine
        book.spine = spine

        # Write EPUB
        output_path.parent.mkdir(parents=True, exist_ok=True)
        epub.write_epub(str(output_path), book, {"epub3_pages": False})
        logger.info(f"Generated EPUB: {output_path}")

        return output_path

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

        raw_name = f"{author_en} - {title_en}{series_suffix}{edition_suffix}"
        safe_name = _sanitize_filename(raw_name)
        return output_dir / f"{safe_name}.epub"

    def _load_css(self) -> str:
        """Load CSS file content."""
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
        series_name: str = "",
        series_order: Optional[int] = None,
        series_total: int = 0,
    ) -> epub.EpubHtml:
        """Build bilingual title page with series info."""
        title_zh_line = ""
        if title_zh and title_zh != title_en:
            title_zh_line = f'    <p class="title-chinese">{_escape(title_zh)}</p>'
        author_zh_line = ""
        if author_zh and author_zh != author_en:
            author_zh_line = f'    <p class="author-chinese">{_escape(author_zh)}</p>'

        series_line = ""
        if series_name and series_order is not None:
            series_line = (
                f'    <p class="series">{_escape(series_name)}'
                f' &mdash; Book {series_order} of {series_total}</p>'
            )

        html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>{_escape(title_en)}</title>
  <link rel="stylesheet" type="text/css" href="styles/kindle.css"/>
</head>
<body>
  <div class="title-page">
    <h1>{_escape(title_en)}</h1>
{title_zh_line}
{series_line}
    <p class="author">{_escape(author_en)}</p>
{author_zh_line}
  </div>
</body>
</html>"""

        item = epub.EpubHtml(
            title="Title Page",
            file_name="title.xhtml",
            lang="en",
        )
        item.set_content(html.encode("utf-8"))
        return item

    def _build_preface(
        self,
        author_en: str,
        css_item: epub.EpubItem,
        build_date: Optional[str] = None,
    ) -> epub.EpubHtml:
        """Build Translator's Preface page with author name and date."""
        if build_date is None:
            build_date = date.today().strftime("%B %Y")

        body_parts = []
        for i, para in enumerate(_PREFACE_PARAGRAPHS):
            text = _escape(para.format(author=author_en))
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

        body_parts = []

        # Chapter heading
        title_html = _escape(title_en)
        title_html = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', title_html)
        title_html = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', title_html)
        title_html = title_html.replace('**', '').replace('*', '')
        heading = f'<h2>{title_html}</h2>'
        body_parts.append(heading)

        chapter_footnotes: List[Dict[str, Any]] = []
        fn_counter = 0
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

        for block_idx, block in enumerate(blocks):
            translated = block.get("translated_content", "")
            content_type = block.get("content_type", "narrative")
            if block_idx in _narr_override:
                content_type = "narrative"
            footnotes = block.get("footnotes", [])

            block_type = block.get("type", "")
            if block_type == "heading":
                continue
            block_title_zh = (chapter.get("title_chinese") or "").strip()
            block_source = (block.get("content") or "").strip()
            if block_idx <= 1 and block_title_zh and block_source == block_title_zh:
                continue

            if not translated:
                continue

            # Remap footnote keys to chapter-level sequential numbering
            old_to_new = {}
            block_footnotes = []
            present_fns = []
            for fn in footnotes:
                old_key = fn.get("key", 0)
                pos = translated.find(f"[{old_key}]")
                if pos == -1:
                    continue
                present_fns.append((pos, fn))
            present_fns.sort(key=lambda x: x[0])
            for _pos, fn in present_fns:
                old_key = fn.get("key", 0)
                fn_counter += 1
                old_to_new[old_key] = fn_counter
                fn_entry = {
                    "key": fn_counter,
                    "epub_id": f"fn-ch{chapter_num}-{fn_counter}",
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
