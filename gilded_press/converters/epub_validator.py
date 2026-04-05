"""Validate EPUB against KDP requirements."""

import logging
import re
import subprocess
from pathlib import Path
from typing import List

import ebooklib
from ebooklib import epub

logger = logging.getLogger(__name__)


def validate_epub(epub_path: Path) -> dict:
    """Validate an EPUB file against KDP requirements.

    Checks:
    - EPUB structure (spine, manifest)
    - TOC (HTML interactive + NCX)
    - Cover image presence
    - Footnote popup structure
    - Image sizes
    - epubcheck (if available)

    Returns:
        Dict with 'valid' bool, 'issues' list, 'warnings' list.
    """
    issues: List[str] = []
    warnings: List[str] = []

    if not epub_path.exists():
        return {"valid": False, "issues": ["EPUB file not found"], "warnings": []}

    try:
        book = epub.read_epub(str(epub_path))
    except Exception as e:
        return {"valid": False, "issues": [f"Cannot read EPUB: {e}"], "warnings": []}

    # Check cover
    has_cover = False
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_COVER or "cover" in item.get_name().lower():
            has_cover = True
            # Check cover image size
            if item.media_type and "image" in item.media_type:
                size_kb = len(item.get_content()) / 1024
                if size_kb > 5000:
                    warnings.append(f"Cover image is {size_kb:.0f} KB (may slow download)")
    if not has_cover:
        issues.append("No cover image found")

    # Check TOC
    toc = book.toc
    if not toc:
        issues.append("No table of contents")
    elif len(toc) < 2:
        warnings.append(f"TOC has only {len(toc)} entries")

    # Check spine
    spine = book.spine
    if not spine:
        issues.append("Empty spine")

    # Check for content documents
    doc_count = 0
    total_size = 0
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            doc_count += 1
            content = item.get_content()
            total_size += len(content)

            # Check for very large documents
            if len(content) > 300000:
                warnings.append(
                    f"{item.get_name()} is {len(content) // 1024} KB "
                    f"(may cause rendering issues)"
                )

    if doc_count == 0:
        issues.append("No content documents found")

    # Check images aren't too large
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_IMAGE:
            size_kb = len(item.get_content()) / 1024
            if size_kb > 10000:
                warnings.append(f"Image {item.get_name()} is {size_kb:.0f} KB")

    # Check footnote structure (epub:type="noteref")
    noteref_count = 0
    footnote_count = 0
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            content = item.get_content().decode("utf-8", errors="ignore")
            noteref_count += len(re.findall(r'epub:type="noteref"', content))
            footnote_count += len(re.findall(r'epub:type="footnote"', content))

    if noteref_count > 0 and footnote_count == 0:
        warnings.append("Found noterefs but no footnote asides")
    if footnote_count > 0:
        logger.info(f"  Footnotes: {footnote_count} asides, {noteref_count} refs")

    # Try epubcheck if available
    epubcheck_result = _run_epubcheck(epub_path)
    if epubcheck_result:
        if epubcheck_result["errors"]:
            issues.extend(epubcheck_result["errors"][:5])
        if epubcheck_result["warnings"]:
            warnings.extend(epubcheck_result["warnings"][:5])

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "stats": {
            "documents": doc_count,
            "total_size_kb": total_size // 1024,
            "footnotes": footnote_count,
            "toc_entries": len(toc) if toc else 0,
        },
    }


def _run_epubcheck(epub_path: Path) -> dict:
    """Run epubcheck if available. Returns None if not installed."""
    try:
        result = subprocess.run(
            ["epubcheck", str(epub_path), "--quiet"],
            capture_output=True, text=True, timeout=60,
        )
        errors = [
            line for line in result.stderr.split("\n")
            if "ERROR" in line
        ]
        warnings = [
            line for line in result.stderr.split("\n")
            if "WARNING" in line
        ]
        return {"errors": errors, "warnings": warnings}
    except FileNotFoundError:
        logger.debug("  epubcheck not found — skipping")
        return None
    except Exception as e:
        logger.debug(f"  epubcheck failed: {e}")
        return None
