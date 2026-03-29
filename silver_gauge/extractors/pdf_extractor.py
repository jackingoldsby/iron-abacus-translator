"""PDF → page images extraction using PyMuPDF."""

import tempfile
from pathlib import Path

import fitz  # PyMuPDF

from silver_gauge.config.defaults import DEFAULT_DPI, DEFAULT_IMAGE_FORMAT


def extract_pages(
    pdf_path: str | Path,
    dpi: int = DEFAULT_DPI,
    page_range: tuple[int, int] | None = None,
    output_dir: Path | None = None,
) -> list[Path]:
    """Extract pages from a PDF as images.

    Args:
        pdf_path: Path to the PDF file.
        dpi: Resolution for rendering (default 150).
        page_range: Optional (start, end) 0-indexed page range, inclusive.
        output_dir: Directory for output images. Uses a temp dir if None.

    Returns:
        List of paths to extracted page images, in page order.
    """
    pdf_path = Path(pdf_path)
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="silver_gauge_"))
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    start = page_range[0] if page_range else 0
    end = page_range[1] if page_range else doc.page_count - 1
    start = max(0, start)
    end = min(doc.page_count - 1, end)

    image_paths = []
    for page_num in range(start, end + 1):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=matrix)
        out_path = output_dir / f"page_{page_num:04d}.{DEFAULT_IMAGE_FORMAT}"
        pix.save(str(out_path))
        image_paths.append(out_path)

    doc.close()
    return image_paths


def get_page_count(pdf_path: str | Path) -> int:
    """Return the number of pages in a PDF."""
    doc = fitz.open(str(pdf_path))
    count = doc.page_count
    doc.close()
    return count


def discover_pdf_parts(directory: str | Path) -> list[Path]:
    """Discover and sort PDF files in a directory by filename.

    Expects filenames like NTUL-9910002853F01_三俠五義_v.1.pdf.
    Returns them sorted so F01 comes before F02 within each volume,
    and volumes are in order (v.1, v.2, v.3, v.4).
    """
    directory = Path(directory)
    pdfs = sorted(directory.glob("*.pdf"))
    return pdfs
