"""Generate KDP metadata from EPUB and catalog."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import ebooklib
from ebooklib import epub

from config.defaults import BISAC_CODES, DEFAULT_KEYWORDS, DEFAULT_CATALOG_DB

logger = logging.getLogger(__name__)


def generate_metadata(
    epub_path: Path,
    catalog_db: Optional[Path] = None,
    genre: str = "wuxia",
    extra_keywords: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Generate KDP upload metadata from EPUB and catalog.

    Returns:
        Dict with all fields needed for KDP upload form.
    """
    catalog_db = catalog_db or DEFAULT_CATALOG_DB
    book = epub.read_epub(str(epub_path))

    # Extract from EPUB metadata
    title = _get_meta(book, "title") or "Untitled"
    author = _get_meta(book, "creator") or "Unknown"
    language = _get_meta(book, "language") or "en"

    # Extract description from preface if available
    description = _extract_description(book)

    # Look up catalog for enrichment
    catalog = _lookup_catalog(title, catalog_db)

    # Build keywords
    keywords = list(DEFAULT_KEYWORDS)
    if catalog.get("category_english"):
        keywords.append(catalog["category_english"])
    if catalog.get("setting_period"):
        keywords.append(catalog["setting_period"])
    if extra_keywords:
        keywords.extend(extra_keywords)
    # KDP allows max 7 keywords
    keywords = list(dict.fromkeys(keywords))[:7]

    # BISAC code
    bisac = BISAC_CODES.get(genre, BISAC_CODES.get("classical", "FIC004000"))

    # Series info
    series = catalog.get("series_name", "")
    series_position = catalog.get("series_order", "")

    # Count chapters/pages estimate
    chapter_count = sum(
        1 for item in book.get_items()
        if item.get_type() == ebooklib.ITEM_DOCUMENT
        and "chapter" in item.get_name()
    )

    metadata = {
        "title": title,
        "subtitle": catalog.get("subtitle", ""),
        "author": author,
        "language": language,
        "description": description,
        "keywords": keywords,
        "bisac_code": bisac,
        "series_name": series,
        "series_position": series_position,
        "chapter_count": chapter_count,
        "ai_disclosure": (
            "This translation was assisted by AI (large language model). "
            "The text has been reviewed, corrected, and annotated with care, "
            "but imperfections from the method may exist."
        ),
        "copyright": "Public domain (original work). Translation copyright the translator.",
        "publisher": "Iron Abacus",
    }

    return metadata


def save_metadata(metadata: Dict[str, Any], output_path: Path) -> Path:
    """Save metadata as JSON for reference during KDP upload."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    logger.info(f"  Metadata saved: {output_path}")
    return output_path


def generate_description_html(metadata: Dict[str, Any]) -> str:
    """Generate HTML book description for KDP product page."""
    parts = []
    if metadata.get("description"):
        for para in metadata["description"].split("\n\n"):
            parts.append(f"<p>{para.strip()}</p>")
    if metadata.get("series_name"):
        parts.append(
            f'<p><em>{metadata["series_name"]}'
            f'{" — Volume " + str(metadata["series_position"]) if metadata.get("series_position") else ""}'
            f"</em></p>"
        )
    return "\n".join(parts)


def _get_meta(book: epub.EpubBook, field: str) -> str:
    """Extract a metadata field from EPUB."""
    values = book.get_metadata("DC", field)
    if values:
        return values[0][0]
    return ""


def _extract_description(book: epub.EpubBook) -> str:
    """Extract book description from preface content."""
    for item in book.get_items():
        if item.get_name() == "preface.xhtml":
            import re
            content = item.get_content().decode("utf-8", errors="ignore")
            # Extract paragraph texts
            paras = re.findall(r"<p[^>]*>(.*?)</p>", content, re.DOTALL)
            # Take first 2-3 paragraphs as description
            desc_parts = []
            for p in paras[:3]:
                text = re.sub(r"<[^>]+>", "", p).strip()
                if text and len(text) > 30:
                    desc_parts.append(text)
            return "\n\n".join(desc_parts)
    return ""


def _lookup_catalog(title: str, db_path: Path) -> dict:
    """Look up work in catalog database."""
    if not db_path.exists():
        return {}
    try:
        import duckdb
        db = duckdb.connect(str(db_path), read_only=True)
        row = db.execute(
            "SELECT title_english, category_english, setting_period "
            "FROM works WHERE title_english = ? LIMIT 1",
            [title],
        ).fetchone()
        db.close()
        if row:
            return {
                "title_english": row[0],
                "category_english": row[1] or "",
                "setting_period": row[2] or "",
            }
    except Exception:
        pass
    return {}
