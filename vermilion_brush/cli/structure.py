"""CLI for structuring Ivory Helm OCR output into Jade Shuttle-compatible JSON.

Reads per-page ocr_merged.json files from the Ivory Helm output directory,
detects 回 boundaries, classifies pages, and emits structured book JSON.

Usage:
    python -m vermilion_brush.cli.structure \
        --strips-dir /path/to/ocr_strips/三俠五義/ \
        --book 三俠五義 \
        --output /path/to/raw_三俠五義.json

    # Dry run — show detected chapters without writing
    python -m vermilion_brush.cli.structure \
        --strips-dir /path/to/ocr_strips/三俠五義/ \
        --book 三俠五義 \
        --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from bronze_mirror.structurers.hui_detector import detect_hui_boundaries
from bronze_mirror.structurers.json_emitter import PageData, emit_raw_json
from bronze_mirror.structurers.page_classifier import PageType, classify_page
from ivory_helm.config.book_config import load_config


def _load_pages(strips_dir: Path) -> list[PageData]:
    """Load all ocr_merged.json files from Ivory Helm output into PageData list."""
    vol_dirs = sorted(d for d in strips_dir.iterdir() if d.is_dir() and d.name.startswith("vol"))
    if not vol_dirs:
        vol_dirs = [strips_dir]

    # First pass: collect all page dirs across volumes for global count
    all_page_dirs = []
    for vol_dir in vol_dirs:
        page_dirs = sorted(
            d for d in vol_dir.iterdir()
            if d.is_dir() and d.name.startswith("page_")
        )
        all_page_dirs.extend(page_dirs)
    total_book_pages = len(all_page_dirs)

    # Second pass: load and classify with global position
    pages = []
    for global_index, page_dir in enumerate(all_page_dirs):
        merged_path = page_dir / "ocr_merged.json"
        merged_txt = page_dir / "ocr_merged.txt"
        detection_path = page_dir / "detection.json"

        # Get text from merged output
        text = ""
        source_pdf = ""
        page_num = 0

        if merged_path.exists():
            with open(merged_path, "r", encoding="utf-8") as f:
                merged = json.load(f)
            text = merged.get("text", "")
            source_pdf = merged.get("source_pdf", "")
            page_num = merged.get("page_num_in_pdf") or 0
        elif merged_txt.exists():
            text = merged_txt.read_text(encoding="utf-8")

        # Fall back to detection.json for provenance
        if not source_pdf and detection_path.exists():
            with open(detection_path, "r", encoding="utf-8") as f:
                det = json.load(f)
            source_pdf = det.get("source_pdf", "")
            page_num = det.get("page_num_in_pdf", 0) or 0

        if not page_num:
            try:
                page_num = int(page_dir.name.split("_")[1])
            except (IndexError, ValueError):
                page_num = 0

        page_type = classify_page(text, global_index, total_book_pages)

        pages.append(PageData(
            text=text,
            page_type=page_type,
            source_pdf=source_pdf,
            page_num_in_pdf=page_num,
            global_page_index=global_index,
        ))

    return pages


def cmd_structure(args: argparse.Namespace) -> None:
    """Structure OCR output into book JSON."""
    strips_dir = Path(args.strips_dir)
    book_id = args.book
    dry_run = args.dry_run

    if not strips_dir.exists():
        print(f"Strips directory not found: {strips_dir}")
        sys.exit(1)

    # Load book config for metadata
    cfg = load_config(book_id)
    metadata = {
        "title": cfg.metadata.title,
        "creator": cfg.metadata.creator,
        "language": cfg.metadata.language,
        "source": cfg.metadata.source,
        "publisher": cfg.metadata.publisher,
    }

    print(f"Loading pages from {strips_dir}...")
    pages = _load_pages(strips_dir)
    print(f"  Loaded {len(pages)} pages")

    # Classify pages
    type_counts = {}
    for p in pages:
        t = p.page_type.value
        type_counts[t] = type_counts.get(t, 0) + 1
    print(f"  Page types: {type_counts}")

    # Detect 回 boundaries
    page_texts = [p.text for p in pages]
    hui_boundaries = detect_hui_boundaries(page_texts)
    print(f"  Detected {len(hui_boundaries)} 回 boundaries")

    if hui_boundaries:
        print(f"  First: {hui_boundaries[0].title}")
        print(f"  Last:  {hui_boundaries[-1].title}")

    # Check for gaps
    hui_nums = [h.hui_number for h in hui_boundaries]
    if hui_nums:
        expected = set(range(1, max(hui_nums) + 1))
        missing = expected - set(hui_nums)
        if missing:
            print(f"  WARNING: Missing 回: {sorted(missing)}")

    if dry_run:
        print("\nDetected chapters:")
        for h in hui_boundaries:
            print(f"  回 {h.hui_number:3d}: {h.title}  (page {pages[h.page_index].source_pdf} p{pages[h.page_index].page_num_in_pdf})")
        return

    # Emit JSON
    result = emit_raw_json(pages, hui_boundaries, metadata)

    output_path = Path(args.output) if args.output else strips_dir / f"raw_{book_id}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total_chars = result.get("number_of_characters", 0)
    num_chapters = len(result.get("chapters", []))
    print(f"\nOutput: {output_path}")
    print(f"  {num_chapters} chapters, {total_chars:,} characters")


def main():
    parser = argparse.ArgumentParser(
        description="Vermilion Brush — structure Ivory Helm OCR output into book JSON"
    )
    parser.add_argument("--strips-dir", required=True, help="Ivory Helm output directory")
    parser.add_argument("--book", help="Book ID (loads config for metadata)")
    parser.add_argument("--output", help="Output JSON path")
    parser.add_argument("--dry-run", action="store_true", help="Show detected chapters only")

    args = parser.parse_args()
    cmd_structure(args)


if __name__ == "__main__":
    main()
