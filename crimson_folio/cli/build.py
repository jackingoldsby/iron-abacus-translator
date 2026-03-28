#!/usr/bin/env python3
"""
CLI for Crimson Folio EPUB Builder

Build EPUB files from translated JSON, optionally with AI-researched
period artwork covers.

Usage:
    python -m cli.build --input translated.json --output book.epub
    python -m cli.build --input translated.json  # auto-names from metadata
    python -m cli.build --input translated.json --cover  # with cover image pipeline
    python -m cli.build --input translated.json --cover-image /path/to/art.jpg
    python -m cli.build --input translated.json --cover-from-portfolio  # from amber_inkstone
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    parser = argparse.ArgumentParser(
        description="Crimson Folio — Build EPUB from translated JSON"
    )
    parser.add_argument("--input", "-i", required=True, help="Input translated JSON file")
    parser.add_argument("--output", "-o", help="Output EPUB file (default: auto from metadata)")
    parser.add_argument("--css", help="Custom CSS file (optional)")
    parser.add_argument("--catalog-db", help="Catalog DB path (default: from config)")
    parser.add_argument(
        "--cover", action="store_true",
        help="Use AI cover pipeline: research period art, search, download, compose",
    )
    parser.add_argument(
        "--cover-image", type=Path,
        help="Use a specific image file as cover (skip AI pipeline)",
    )
    parser.add_argument(
        "--cover-from-portfolio", action="store_true",
        help="Look up assigned cover from amber_inkstone artwork_portfolio.duckdb",
    )
    parser.add_argument(
        "--theme", default="kindle",
        choices=["kindle", "modern", "minimal"],
        help="CSS theme (default: kindle)",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {input_path} not found")
        return 1

    output_path = Path(args.output) if args.output else None
    css_path = Path(args.css) if args.css else None
    catalog_db = Path(args.catalog_db) if args.catalog_db else None

    # Resolve theme CSS if no explicit CSS given
    if not css_path and args.theme != "kindle":
        theme_css = Path(__file__).parent.parent / "styles" / f"{args.theme}.css"
        if theme_css.exists():
            css_path = theme_css

    # Handle cover image
    cover_image = args.cover_image

    if args.cover_from_portfolio and not cover_image:
        cover_image = _lookup_portfolio_cover(input_path)

    if args.cover and not cover_image:
        cover_image = _run_cover_pipeline(input_path)

    from builders.epub_builder import EpubBuilder

    builder = EpubBuilder(
        css_path=css_path,
        catalog_db=catalog_db,
        cover_image=cover_image,
    )
    result = builder.build(input_path, output_path)
    size_kb = result.stat().st_size / 1024
    print(f"Generated: {result} ({size_kb:.1f} KB)")
    return 0


def _lookup_portfolio_cover(input_path: Path) -> Path | None:
    """Look up assigned cover image from amber_inkstone portfolio DB.

    Reads artwork_assignments + artwork_images from artwork_portfolio.duckdb.
    No Python imports from amber_inkstone — just a direct DuckDB read.
    """
    import json

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    work_number = data.get("meta", {}).get("work_number", "")
    if not work_number:
        return None

    portfolio_db = Path("/Users/jacki/project_files/translation_project/db/artwork_portfolio.duckdb")
    if not portfolio_db.exists():
        print("  Portfolio DB not found — skipping portfolio lookup")
        return None

    try:
        import duckdb

        conn = duckdb.connect(str(portfolio_db), read_only=True)
        row = conn.execute("""
            SELECT i.cached_path
            FROM artwork_assignments a
            JOIN artwork_images i ON a.image_id = i.image_id
            WHERE a.work_number = ?
        """, (work_number,)).fetchone()
        conn.close()

        if row and row[0]:
            cached = Path(row[0])
            if cached.exists():
                print(f"  Portfolio cover: {cached}")
                return cached
            else:
                print(f"  Portfolio image not found on disk: {cached}")
        else:
            print(f"  No portfolio assignment for {work_number}")

    except Exception as e:
        print(f"  Portfolio lookup failed: {e}")

    return None


def _run_cover_pipeline(input_path: Path) -> Path | None:
    """Run the full cover image pipeline: research → search → download → compose."""
    import json

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("meta", {})
    work_number = meta.get("work_number", "unknown")

    print(f"Cover pipeline: researching art for {work_number}...")

    try:
        from covers.researcher import CoverResearcher
        from covers.searcher import CoverSearcher
        from covers.downloader import CoverDownloader
        from covers.composer import CoverComposer

        # Step 1: Research
        researcher = CoverResearcher()
        suggestions = researcher.suggest_searches(meta)
        if not suggestions:
            print("  No cover suggestions generated")
            return None

        # Step 2: Search
        searcher = CoverSearcher()
        all_results = []
        for suggestion in suggestions:
            print(f"  Searching: {suggestion.query}")
            results = searcher.search_all(suggestion.query, limit=3)
            all_results.extend(results)

        if not all_results:
            print("  No images found")
            return None

        # Step 3: Download first valid candidate
        downloader = CoverDownloader()
        downloaded = None
        for result in all_results:
            print(f"  Trying: {result.title} ({result.source})")
            path = downloader.download(result.url, work_number)
            if path:
                downloaded = path
                break

        if not downloaded:
            print("  No valid images downloaded")
            return None

        # Step 4: Compose
        title_en = meta.get("translation", {}).get("title", meta.get("title", ""))
        title_zh = meta.get("title", "")
        author_en = meta.get("translation", {}).get("author", meta.get("author", ""))
        author_zh = meta.get("author", "")

        composer = CoverComposer()
        cover_path = composer.compose(
            downloaded,
            title_en=title_en,
            title_zh=title_zh,
            author_en=author_en,
            author_zh=author_zh,
        )
        print(f"  Cover composed: {cover_path}")
        return cover_path

    except Exception as e:
        print(f"  Cover pipeline failed: {e}")
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
