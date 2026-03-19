#!/usr/bin/env python3
"""
EPUB3 Builder for Translated Wuxia Novels

Produces Kindle-ready EPUB3 files with:
- Popup footnotes (EPUB3 aside + epub:type="footnote")
- Content-type-aware formatting (narrative, dialogue, verse, document, thought)
- Bilingual title page
- NCX + EPUB3 nav table of contents
- Glossary appendix

Usage:
    from processors.epub_builder import EpubBuilder

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

logger = logging.getLogger(__name__)

# CSS path relative to this file
_DEFAULT_CSS_PATH = Path(__file__).parent.parent / "styles" / "kindle.css"

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

_COLOPHON_PARAGRAPHS = [
    "The original Chinese source text is embedded in this file as HTML5 data"
    " attributes. Each source paragraph is stored in a data-zh attribute on"
    " the first English paragraph derived from it. Where one Chinese paragraph"
    " expands to multiple English paragraphs, they share a data-zh-block"
    " identifier for grouping.",
    "Anyone who unpacks the EPUB can extract the bilingual alignment."
    " This is intentional \u2014 it allows readers with Chinese literacy"
    " to cross-reference the translation against the source, and makes"
    " the file useful as a study aid.",
]


def _default_catalog_path() -> Path:
    from utils.environment_config import get_or_create_config
    return get_or_create_config().catalog_path


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

    def __init__(self, css_path: Optional[Path] = None, catalog_db: Optional[Path] = None):
        self.css_path = css_path or _DEFAULT_CSS_PATH
        self.catalog_db = catalog_db or _default_catalog_path()
        self._catalog_cache: Dict[str, Dict[str, Any]] = {}

    def _get_catalog(self, work_number: str) -> Dict[str, Any]:
        """Cached catalog lookup."""
        if work_number not in self._catalog_cache:
            self._catalog_cache[work_number] = self._lookup_catalog(work_number)
        return self._catalog_cache[work_number]

    def _resolve_english_meta(self, meta: Dict[str, Any]) -> tuple:
        """Return (title_en, author_en) using translation meta with catalog fallback.

        Priority order:
        1. meta.title_english / meta.author_english (set by Stage 2 metadata translation)
        2. meta.translation.title / meta.translation.author (legacy format)
        3. Catalog DB lookup by work_number
        4. Chinese title/author as last resort
        """
        work_number = meta.get("work_number", "unknown")
        catalog = self._get_catalog(work_number)

        # Stage 2 stores translated values as title_english / author_english
        title_en = meta.get("title_english", "") or meta.get("translation", {}).get("title", "")
        author_en = meta.get("author_english", "") or meta.get("translation", {}).get("author", "")
        catalog_title = catalog.get("title_english", "")
        catalog_author = catalog.get("author_english", "")

        # Strip footnote markers from translated metadata (e.g. "The Sword of the Yue Maiden[1]")
        if title_en:
            title_en = re.sub(r'\[\d+\]', '', title_en).strip()
        if author_en:
            author_en = re.sub(r'\[\d+\]', '', author_en).strip()

        # Fall back to catalog if translation meta is missing, matches Chinese, or is suspiciously long
        if not title_en or title_en == meta.get("title") or len(title_en) > 80:
            title_en = catalog_title or meta.get("title", "Untitled")
        if not author_en or author_en == meta.get("author"):
            author_en = catalog_author or meta.get("author", "Unknown")

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
        series_info = self._lookup_series(work_number)
        series_name = series_info.get("name", "")
        series_order = series_info.get("order")
        series_total = series_info.get("total", 0)

        # Build full EPUB title: "Title (Series #02)"
        epub_title = title_en
        if series_name and series_order is not None:
            width = len(str(series_total)) if series_total >= 10 else 2
            epub_title = f"{title_en} ({series_name} #{series_order:0{width}d})"

        # Create EPUB book
        book = epub.EpubBook()
        book.set_identifier(f"wuxia-{work_number}")
        book.set_title(epub_title)
        book.set_language("en")
        book.add_author(author_en)

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

        # Build colophon (publishing note on embedded source text)
        colophon_page = self._build_colophon(css_item)
        book.add_item(colophon_page)

        # Build chapters
        chapter_items = []
        spine = ["nav", title_page, preface_page, colophon_page]

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
            epub.Link(colophon_page.file_name, "About This Edition", "colophon"),
        ]
        for ch_idx, ch_item in enumerate(chapter_items):
            ch = chapters[ch_idx]
            ch_title = ch.get("title_english") or ch.get("translated_title") or ""
            if not ch_title:
                ch_title = self._translate_chapter_title(
                    ch.get("title", ""), ch_idx + 1
                )
            # Strip footnote markers and markdown asterisks from TOC text
            ch_title_clean = re.sub(r'\[\d+\]', '', ch_title).strip()
            ch_title_clean = ch_title_clean.replace("*", "")
            # Link to the chapter heading anchor, not just the file
            toc_entries.append(
                epub.Link(
                    f"{ch_item.file_name}#ch-heading",
                    ch_title_clean,
                    ch_item.id,
                )
            )
        if glossary_item:
            toc_entries.append(
                epub.Link(glossary_item.file_name, "Glossary of Terms", "glossary")
            )
        book.toc = toc_entries

        # Add navigation files
        book.add_item(epub.EpubNcx())
        nav = epub.EpubNav()
        nav.add_item(css_item)
        book.add_item(nav)

        # Set spine
        book.spine = spine

        # Write EPUB
        output_path.parent.mkdir(parents=True, exist_ok=True)
        epub.write_epub(str(output_path), book)
        logger.info(f"Generated EPUB: {output_path}")

        return output_path

    # Chinese numeral → int mapping for chapter title translation
    _CHINESE_NUMS = {
        "〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        "百": 100, "千": 1000,
        "廿": 20, "卅": 30, "卌": 40,
    }

    def _parse_chinese_num(self, s: str) -> Optional[int]:
        """Parse a Chinese numeral string like 十七 → 17, 卅二 → 32."""
        nums = self._CHINESE_NUMS
        if not s:
            return None
        # Single character
        if len(s) == 1 and s in nums:
            return nums[s]
        # Try to parse compound numerals
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

        # Match 第N回, 第N章, 第N節 patterns
        m = re.match(r"第(.+?)(回|章|節|篇|卷)", zh_title)
        if m:
            num_str = m.group(1)
            type_char = m.group(2)
            parsed = self._parse_chinese_num(num_str)
            type_map = {"回": "Chapter", "章": "Chapter", "節": "Section",
                        "篇": "Part", "卷": "Volume"}
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
        e.g.  Jin Yong - The Flying Fox of Snowy Mountain (Fox Volant Duology #01).epub
        """
        meta = data.get("meta", {})
        work_number = meta.get("work_number", "unknown")
        title_en, author_en = self._resolve_english_meta(meta)

        series_info = self._lookup_series(work_number)
        series_suffix = ""
        if series_info.get("name") and series_info.get("order") is not None:
            total = series_info["total"]
            width = len(str(total)) if total >= 10 else 2
            series_suffix = f" ({series_info['name']} #{series_info['order']:0{width}d})"

        raw_name = f"{author_en} - {title_en}{series_suffix}"
        safe_name = _sanitize_filename(raw_name)
        return output_dir / f"{safe_name}.epub"

    def _lookup_catalog(self, work_number: str) -> Dict[str, Any]:
        """Look up title, author, and series info from catalog DB."""
        if not self.catalog_db or not self.catalog_db.exists():
            return {}
        try:
            from utils.db import connect_catalog
            conn = connect_catalog(self.catalog_db)
            cur = conn.cursor()
            # Fetch title/author + series in one query (LEFT JOIN so non-series works still return)
            cur.execute("""
                SELECT w.title_english, w.author_english,
                       s.name_english, ws.order_in_series,
                       (SELECT COUNT(*) FROM work_series ws2
                        WHERE ws2.series_id = ws.series_id) as total
                FROM works w
                LEFT JOIN work_series ws ON w.work_id = ws.work_id
                LEFT JOIN series s ON ws.series_id = s.series_id
                WHERE w.work_number = ?
            """, (work_number,))
            row = cur.fetchone()
            conn.close()
            if row:
                result = {
                    "title_english": row[0] or "",
                    "author_english": row[1] or "",
                }
                if row[2]:  # series name
                    result["series_name"] = row[2]
                    result["series_order"] = row[3]
                    result["series_total"] = row[4]
                return result
        except Exception as e:
            logger.warning(f"Catalog lookup failed for {work_number}: {e}")
        return {}

    def _lookup_series(self, work_number: str) -> Dict[str, Any]:
        """Look up series info from catalog DB by work_number."""
        catalog = self._lookup_catalog(work_number)
        if catalog.get("series_name"):
            return {
                "name": catalog["series_name"],
                "order": catalog["series_order"],
                "total": catalog["series_total"],
            }
        return {}

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
        # Only show Chinese subtitle if different from English title
        title_zh_line = ""
        if title_zh and title_zh != title_en:
            title_zh_line = f'    <p class="title-chinese">{_escape(title_zh)}</p>'
        author_zh_line = ""
        if author_zh and author_zh != author_en:
            author_zh_line = f'    <p class="author-chinese">{_escape(author_zh)}</p>'

        series_line = ""
        if series_name and series_order is not None:
            width = len(str(series_total)) if series_total >= 10 else 2
            series_line = (
                f'    <p class="series">{_escape(series_name)}'
                f' &mdash; Book {series_order:0{width}d} of {series_total}</p>'
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

        body_parts.append(f'    <p class="signature">Iron Abacus</p>')
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

    def _build_colophon(self, css_item: epub.EpubItem) -> epub.EpubHtml:
        """Build 'About This Edition' back-matter page."""
        body_parts = []
        for para in _COLOPHON_PARAGRAPHS:
            body_parts.append(f"    <p>{_escape(para)}</p>")

        body_html = "\n".join(body_parts)
        html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>About This Edition</title>
  <link rel="stylesheet" type="text/css" href="styles/kindle.css"/>
</head>
<body>
  <div class="colophon">
    <h2>About This Edition</h2>
{body_html}
  </div>
</body>
</html>"""

        item = epub.EpubHtml(
            title="About This Edition",
            file_name="colophon.xhtml",
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
        title_zh = chapter.get("title", "")
        title_en = chapter.get("title_english") or chapter.get("translated_title") or ""
        if not title_en:
            # Generate English title from Chinese 第N回/章 pattern or fall back
            title_en = self._translate_chapter_title(title_zh, chapter_num)
        blocks = chapter.get("content_blocks", [])

        # Build body content
        body_parts = []

        # Chapter heading — strip footnote markers, markdown bold/italic
        title_html = re.sub(r'\[\d+\]', '', title_en).strip()
        title_html = _escape(title_html)
        title_html = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', title_html)
        title_html = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', title_html)
        title_html = title_html.replace('**', '').replace('*', '')
        heading = f'<h2 id="ch-heading">{title_html}'
        if title_zh:
            heading += f'<span class="chapter-chinese">{_escape(title_zh)}</span>'
        heading += '</h2>'
        body_parts.append(heading)

        # Collect all footnotes for end-of-chapter rendering
        chapter_footnotes: List[Dict[str, Any]] = []
        fn_counter = 0
        prev_content_type: Optional[str] = None

        for block_idx, block in enumerate(blocks):
            translated = block.get("translated_content", "")
            content_type = block.get("content_type", "narrative")
            footnotes = block.get("footnotes", [])

            # Skip first block if its source text IS the chapter heading
            # (The body translator and heading translator produce different
            #  English wordings, so compare the Chinese source instead.)
            if block_idx == 0:
                block_source = block.get("content", "").strip()
                chapter_title_zh = chapter.get("title", "").strip()
                if block_source and chapter_title_zh and block_source == chapter_title_zh:
                    continue

            if not translated:
                # Render section-break blocks as <hr>
                # Covers: ※※※, ＊＊＊, ☆☆☆, ◇, ──, －－, etc.
                raw = block.get("content", "").strip()
                if raw and all(c in "※＊*☆◇◆○●□■─━──－\u3000 \t" for c in raw):
                    body_parts.append('<hr class="scene-break"/>')
                continue

            # Remap footnote keys to chapter-level sequential numbering
            # Only include footnotes whose [key] marker exists in text
            old_to_new = {}
            block_footnotes = []
            for fn in footnotes:
                old_key = fn.get("key", 0)
                if f"[{old_key}]" not in translated:
                    continue
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

            # Original Chinese source for data-zh attribute
            # data-zh carries the full Chinese text on the first EN paragraph;
            # data-zh-block groups all EN paragraphs from the same source block
            zh_source = _escape(block.get("content", ""))
            zh_block_id = block.get("id", f"b{block_idx}")
            zh_attr_full = (
                f' data-zh="{zh_source}" data-zh-block="{zh_block_id}"'
                if zh_source else ""
            )
            zh_attr_ref = (
                f' data-zh-block="{zh_block_id}"'
                if zh_source else ""
            )

            # Verse/document: render as before without splitting
            if content_type in ("verse", "document"):
                rendered_text = self._render_text_with_noterefs(
                    translated, old_to_new, chapter_num
                )
                body_parts.append(
                    self._wrap_content_type(
                        rendered_text, content_type, zh_attr=zh_attr_full,
                    )
                )
                prev_content_type = content_type
                continue

            # Split raw text into dialogue/narrative segments before
            # HTML escaping (quotes are lost after _escape).
            raw_segments = self._split_dialogue_segments(translated)

            _speech = {"dialogue"}
            _prose = {"narrative", "descriptive"}

            for seg_idx, raw_seg in enumerate(raw_segments):
                # Determine CSS class: if segment starts with a quote
                # char, tag it as dialogue; otherwise use block type
                seg_class = content_type
                if raw_seg and raw_seg[0] in '"\u201c':
                    seg_class = "dialogue"
                elif content_type == "dialogue" and raw_seg and raw_seg[0] not in '"\u201c':
                    seg_class = "narrative"

                # Detect transition from previous paragraph
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
                # First segment: full Chinese source + block ID
                # Subsequent segments: block ID only (for grouping)
                seg_zh = zh_attr_full if seg_idx == 0 else zh_attr_ref
                body_parts.append(
                    f'<p class="{seg_class}"{t_style}{seg_zh}>{rendered_seg}</p>'
                )

        # Render footnotes at chapter end
        if chapter_footnotes:
            body_parts.append(
                self._render_chapter_footnotes(chapter_footnotes)
            )

        # Assemble XHTML
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
        """
        Replace [N] markers with EPUB3 noteref links.

        [1] -> <a epub:type="noteref" href="#fn-ch3-7">[7]</a>
        """
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

        escaped = _escape(text)
        # Ensure space before every [N] marker (unless already preceded by space/quote)
        escaped = re.sub(r'(?<=[^\s"\u201c])\[(\d+)\]', r' [\1]', escaped)
        result = re.sub(r'\[(\d+)\]', replace_marker, escaped)
        # Fix unpaired asterisks before italic conversion.
        # Word* without opening * → *Word*  (e.g. Shīxiōng* → *Shīxiōng*)
        result = re.sub(r'(?<!\*)\b(\w+)\*(?!\*)', r'*\1*', result)
        # *Word without closing * → *Word*
        result = re.sub(r'(?<!\*)\*(\w+)\b(?!\*)', r'*\1*', result)
        # Convert **bold** to <strong> (before italics to avoid conflict)
        result = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', result)
        # Convert *italics* to <em>, but only for short spans (≤ 3 words).
        # Longer spans are almost certainly unpaired asterisk bugs.
        def _italic_if_short(m):
            content = m.group(1)
            if len(content.split()) <= 3:
                return f'<em>{content}</em>'
            return content  # strip the asterisks, don't italicize
        result = re.sub(r'\*([^*]+)\*', _italic_if_short, result)
        # Strip any orphan asterisks
        result = result.replace('**', '').replace('*', '')
        return result

    @staticmethod
    def _split_dialogue_segments(text: str) -> List[str]:
        """Split a block into dialogue and narrative segments.

        Each quoted speech line (with its attribution if present)
        becomes its own segment.  Narrative passages between quotes
        also become separate segments.

        Handles split quotes: "start," he said, "end." stays as one unit.
        Attribution: "speech," he said. stays together.
        """
        # Split on explicit blank lines first
        if "\n\n" in text:
            return [s.strip() for s in text.split("\n\n") if s.strip()]

        import re
        Q_OPEN = '"\u201c'
        Q_CLOSE = '"\u201d'

        # Tokenize into quoted and unquoted spans
        # This handles nested split quotes properly
        tokens: List[dict] = []
        i = 0
        while i < len(text):
            if text[i] in Q_OPEN:
                # Find closing quote
                j = i + 1
                while j < len(text) and text[j] not in Q_CLOSE:
                    j += 1
                if j < len(text):
                    j += 1  # include closing quote
                tokens.append({"type": "quote", "text": text[i:j], "start": i})
                i = j
            else:
                # Unquoted text — read until next opening quote or end
                j = i
                while j < len(text) and text[j] not in Q_OPEN:
                    j += 1
                tokens.append({"type": "narr", "text": text[i:j], "start": i})
                i = j

        # Now merge tokens into segments:
        # - A quote ending with , + narr + quote = split quote (merge all three)
        # - A quote ending with , + narr ending with . = quote + attribution (merge both)
        # - A quote ending with .!? = standalone dialogue
        # - Narr alone = narrative segment
        # Pre-pass: merge inline quoted terms into surrounding narr.
        # An inline quote is short (< 30 chars) and the content inside
        # doesn't look like dialogue (no sentence-ending punct before
        # the closing quote).
        merged_tokens: List[dict] = []
        for tok in tokens:
            if (tok["type"] == "quote"
                    and merged_tokens
                    and merged_tokens[-1]["type"] == "narr"):
                inner = tok["text"].strip().strip('"\u201c\u201d')
                inner_core = inner.rstrip('.!?, ')
                # Inline term: very short content (< 10 chars stripped of
                # punct), or short (< 30 chars) with no sentence punct.
                is_inline = (
                    len(inner_core) < 10
                    or (len(inner) < 30
                        and not any(inner.rstrip().endswith(p) for p in '.!?'))
                )
                if is_inline:
                    # Peek: if next token is also narr, likely inline
                    merged_tokens[-1]["text"] += tok["text"]
                    merged_tokens[-1]["type"] = "narr"
                    continue
            # Merge consecutive narr tokens (from inline quote merging)
            if (tok["type"] == "narr"
                    and merged_tokens
                    and merged_tokens[-1]["type"] == "narr"):
                merged_tokens[-1]["text"] += tok["text"]
                continue
            merged_tokens.append(dict(tok))
        tokens = merged_tokens

        def _ends_with_comma(q_text):
            """Check if quoted text ends with ," (comma before close-quote)."""
            s = q_text.rstrip()
            return len(s) >= 2 and s[-2] == ','

        segments: List[str] = []
        idx = 0
        while idx < len(tokens):
            tok = tokens[idx]

            if tok["type"] == "quote":
                merged = tok["text"]

                if _ends_with_comma(merged):
                    # Comma ending: split quote or attribution follows.
                    # Split quote: "...," action-beat, "continuation"
                    #   action-beat does NOT end with .!?
                    # Attribution: "...," he said.
                    #   attribution DOES end with .!?
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

                # Attach trailing attribution to comma-ended quote
                if (_ends_with_comma(merged)
                        and idx + 1 < len(tokens)
                        and tokens[idx + 1]["type"] == "narr"):
                    narr_text = tokens[idx + 1]["text"].strip()
                    if not narr_text:
                        idx += 1
                    elif narr_text[-1] in '.!?':
                        merged += tokens[idx + 1]["text"]
                        idx += 1

                segments.append(merged.strip())

            else:
                # Narrative segment.
                narr = tok["text"]
                # If narr ends with comma (e.g. "he said,") attach the
                # following quote as introductory attribution.
                if (narr.rstrip().endswith(',')
                        and idx + 1 < len(tokens)
                        and tokens[idx + 1]["type"] == "quote"):
                    narr += tokens[idx + 1]["text"]
                    idx += 1
                    # The attached quote might itself have attribution
                    qt = tokens[idx]["text"] if idx < len(tokens) and tokens[idx]["type"] == "quote" else narr
                    # Check if the whole thing now ends with ,"
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
        self, html_text: str, content_type: str, *,
        transition: bool = False, zh_attr: str = "",
    ) -> str:
        """Wrap rendered text in content-type-appropriate HTML."""
        # Extra top margin at narrative/descriptive <-> dialogue boundaries
        t_style = ' style="margin-top:0.8em"' if transition else ""
        if content_type == "verse":
            lines = html_text.split("\n")
            inner = "".join(f"<p>{line}</p>" for line in lines if line.strip())
            return f'<div class="verse"{t_style}{zh_attr}>{inner}</div>'
        elif content_type == "document":
            return f'<blockquote class="document"{t_style}{zh_attr}>{html_text}</blockquote>'
        else:
            css_class = content_type if content_type in (
                "dialogue", "narrative", "descriptive", "thought"
            ) else "narrative"
            segments = self._split_dialogue_segments(html_text)
            parts = []
            for idx, seg in enumerate(segments):
                style = t_style if idx == 0 else ""
                # Tag segments that start with a quote as dialogue
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
        """
        Render footnotes as EPUB3 aside elements for popup support,
        plus a visible section for fallback readers.
        """
        parts = []

        # Footnote section — visible on all readers including Kindle.
        # Each entry uses epub:type="footnote" on a <div> so Kindle can
        # also show it as a popup when tapped via a noteref link.
        parts.append('<section class="chapter-footnotes">')
        parts.append('<h3>Notes</h3>')
        for fn in footnotes:
            fn_id = fn["epub_id"]
            ref_id = fn_id.replace("fn-", "fnref-")
            ideogram = _escape(fn.get("ideogram", ""))
            pinyin = _escape(fn.get("pinyin", ""))
            explanation = _escape(fn.get("explanation", ""))

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

    def _build_glossary(
        self,
        entries: List[Any],
        css_item: epub.EpubItem,
    ) -> epub.EpubHtml:
        """Build glossary appendix chapter."""
        # Group by category
        from utils.epub_glossary_generator import group_by_category
        groups = group_by_category(entries)

        parts = ['<section class="glossary">', '<h2>Glossary of Terms</h2>']

        for category, cat_entries in groups.items():
            parts.append(f'<div class="glossary-category">')
            parts.append(f'<h3>{_escape(category)}</h3>')

            for entry in cat_entries:
                ideogram = _escape(entry.ideogram)
                pinyin = _escape(entry.pinyin)
                explanation = _escape(entry.explanation)

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
    # Replace path-unsafe chars
    name = re.sub(r'[\\/:*?"<>|]', '', name)
    # Collapse multiple spaces
    name = re.sub(r'\s+', ' ', name).strip()
    # Truncate to reasonable length
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


def main():
    """CLI entry point."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python processors/epub_builder.py <input.json> [output.epub]")
        return 1

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else None

    builder = EpubBuilder()
    result = builder.build(input_path, output_path)
    print(f"Generated: {result}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    exit(main())
