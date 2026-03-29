"""Assemble OCR pages into Jade Shuttle-compatible raw JSON."""

import re
from dataclasses import dataclass

from bronze_mirror.structurers.hui_detector import HuiBoundary
from bronze_mirror.structurers.page_classifier import PageType


@dataclass
class PageData:
    """OCR result for a single page with metadata."""

    text: str
    page_type: PageType
    source_pdf: str  # Filename of the source PDF
    page_num_in_pdf: int  # 0-indexed page number within that PDF
    global_page_index: int  # Index across all merged PDFs


def _split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs on sentence-ending punctuation sequences or blank lines."""
    # Split on blank lines first
    chunks = re.split(r"\n\s*\n", text)

    paragraphs = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        # Further split on sentence-ending punctuation followed by newline
        parts = re.split(r"(?<=[。！？」』])\n", chunk)
        for part in parts:
            part = part.strip().replace("\n", "")
            if part:
                paragraphs.append(part)

    return paragraphs


def _extract_section_text(
    pages: list[PageData],
    start_page: int,
    start_offset: int,
    end_page: int,
    end_offset: int | None,
) -> tuple[str, list[tuple[str, str]]]:
    """Extract text between two boundaries, tracking source provenance.

    Returns:
        (merged_text, [(source_pdf, page_num), ...])
    """
    text_parts = []
    provenance: list[tuple[str, int]] = []

    for idx in range(start_page, min(end_page + 1, len(pages))):
        page = pages[idx]
        page_text = page.text

        if idx == start_page:
            page_text = page_text[start_offset:]
        if idx == end_page and end_offset is not None:
            page_text = page_text[:end_offset]

        if page_text.strip():
            text_parts.append(page_text)
            provenance.append((page.source_pdf, page.page_num_in_pdf))

    merged = "\n".join(text_parts)
    return merged, provenance


def emit_raw_json(
    pages: list[PageData],
    hui_boundaries: list[HuiBoundary],
    metadata: dict,
) -> dict:
    """Produce Jade Shuttle raw JSON from OCR pages and detected boundaries.

    Args:
        pages: All OCR'd pages with classification and provenance.
        hui_boundaries: Detected chapter boundaries.
        metadata: Work metadata (title, creator, etc.).

    Returns:
        Dict matching the Jade Shuttle raw JSON contract.
    """
    # Collect front matter (preface pages before first hui)
    first_hui_page = hui_boundaries[0].page_index if hui_boundaries else len(pages)
    front_matter_pages = [
        p for p in pages[:first_hui_page] if p.page_type == PageType.PREFACE
    ]

    chapters = []
    toc = []

    # Front matter sections
    if front_matter_pages:
        fm_text = "\n".join(p.text for p in front_matter_pages)
        fm_paragraphs = _split_paragraphs(fm_text)
        if fm_paragraphs:
            fm_source_pdf = front_matter_pages[0].source_pdf
            fm_pages_range = f"{front_matter_pages[0].page_num_in_pdf}"
            if len(front_matter_pages) > 1:
                fm_pages_range += f"-{front_matter_pages[-1].page_num_in_pdf}"

            chapters.append({
                "title": "前言",
                "content": [
                    {
                        "tag": "p",
                        "content": para,
                        "source_pdf": fm_source_pdf,
                        "source_pages": fm_pages_range,
                    }
                    for para in fm_paragraphs
                ],
            })
            toc.append({"full_title": "前言", "chapter_ref": "chapter_0"})

    # Hui chapters
    for i, hui in enumerate(hui_boundaries):
        # Determine end boundary
        if i + 1 < len(hui_boundaries):
            next_hui = hui_boundaries[i + 1]
            end_page = next_hui.page_index
            end_offset = next_hui.char_offset
        else:
            end_page = len(pages) - 1
            end_offset = None

        merged_text, provenance = _extract_section_text(
            pages, hui.page_index, hui.char_offset, end_page, end_offset
        )

        # Remove the hui header from the body text
        merged_text = re.sub(
            r"^第[一二三四五六七八九十百零廿卅]+回\s*[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+",
            "",
            merged_text,
            count=1,
        ).strip()

        paragraphs = _split_paragraphs(merged_text)

        # Build content blocks with provenance
        content_blocks = []
        if provenance:
            source_pdfs = list(dict.fromkeys(p[0] for p in provenance))
            page_nums = [p[1] for p in provenance]
            default_pdf = source_pdfs[0]
            page_range = (
                str(page_nums[0])
                if len(page_nums) == 1
                else f"{page_nums[0]}-{page_nums[-1]}"
            )

            for para in paragraphs:
                content_blocks.append({
                    "tag": "p",
                    "content": para,
                    "source_pdf": default_pdf,
                    "source_pages": page_range,
                })

        chapter_idx = len(chapters)
        chapters.append({
            "title": hui.title,
            "content": content_blocks,
        })
        toc.append({
            "full_title": hui.title,
            "chapter_ref": f"chapter_{chapter_idx}",
        })

    # Compute total character count
    total_chars = sum(
        len(block.get("content", ""))
        for ch in chapters
        for block in ch["content"]
    )

    # Determine source label
    source_pdfs = list(dict.fromkeys(p.source_pdf for p in pages))
    source_label = ", ".join(source_pdfs) if len(source_pdfs) <= 3 else f"{source_pdfs[0]} ... ({len(source_pdfs)} files)"

    return {
        "metadata": {
            "title": metadata.get("title", ""),
            "creator": metadata.get("creator", ""),
            "language": metadata.get("language", "zh-Hant"),
            "source": metadata.get("source", f"OCR from {source_label}"),
            "publisher": metadata.get("publisher"),
        },
        "source": source_label,
        "number_of_characters": total_chars,
        "toc": toc,
        "chapters": chapters,
    }
