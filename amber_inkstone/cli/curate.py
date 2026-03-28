#!/usr/bin/env python3
"""
CLI: curate — build and refresh the period artwork portfolio.

Usage:
    python -m cli.curate --list-periods
    python -m cli.curate --period "Ming Dynasty" --limit 20
    python -m cli.curate --period "Ming Dynasty" --dry-run
    python -m cli.curate --all --limit 10
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from catalog.period_grouper import group_works_by_period
from catalog.portfolio_db import PortfolioDB
from config.dynasty_periods import DYNASTY_PERIODS, normalize_period


def main():
    parser = argparse.ArgumentParser(
        description="Amber Inkstone — Period artwork portfolio curator"
    )
    parser.add_argument(
        "--list-periods", action="store_true",
        help="List all period groups from catalog with work counts",
    )
    parser.add_argument(
        "--period", type=str,
        help="Build portfolio for a specific period (e.g. 'Ming Dynasty')",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Build portfolio for all periods with known dynasty data",
    )
    parser.add_argument(
        "--limit", type=int, default=10,
        help="Max images to download per period (default: 10)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show research and queries without downloading",
    )
    parser.add_argument(
        "--catalog-db", type=Path,
        help="Override catalog DB path",
    )
    parser.add_argument(
        "--portfolio-db", type=Path,
        help="Override portfolio DB path",
    )

    args = parser.parse_args()

    if args.list_periods:
        return _list_periods(args.catalog_db)

    if args.period:
        slug, label = normalize_period(args.period)
        if slug == "unspecified":
            # Try matching raw text against known labels
            for s, (l, _, _) in DYNASTY_PERIODS.items():
                if l.lower() == args.period.lower():
                    slug, label = s, l
                    break
            else:
                print(f"Could not resolve period: {args.period}")
                print("Use --list-periods to see available periods")
                return 1

        return _curate_period(slug, label, args.limit, args.dry_run, args.portfolio_db,
                              catalog_db=args.catalog_db)

    if args.all:
        return _curate_all(args.limit, args.dry_run, args.catalog_db, args.portfolio_db)

    parser.print_help()
    return 0


def _list_periods(catalog_db):
    """List all period groups with work counts."""
    groups = group_works_by_period(catalog_db)

    if not groups:
        print("No works found in catalog.")
        return 1

    # Also show existing portfolio counts
    try:
        db = PortfolioDB()
        portfolio_counts = db.count_by_period()
    except Exception:
        portfolio_counts = {}

    print(f"\n{'Period':<35} {'Works':>6} {'Images':>7}")
    print("-" * 52)

    for g in groups:
        img_count = portfolio_counts.get(g.period_slug, {}).get("count", 0)
        img_str = str(img_count) if img_count else "-"
        print(f"{g.period_label:<35} {g.work_count:>6} {img_str:>7}")

    total_works = sum(g.work_count for g in groups)
    total_images = sum(v.get("count", 0) for v in portfolio_counts.values())
    print("-" * 52)
    print(f"{'Total':<35} {total_works:>6} {total_images:>7}")
    print()
    return 0


def _curate_period(period_slug, period_label, limit, dry_run, portfolio_db_path,
                   catalog_db=None):
    """Run the full curation pipeline for a single period."""
    print(f"\nCurating: {period_label} (slug: {period_slug})")

    db = PortfolioDB(portfolio_db_path)

    # Extract thematic context from catalog
    from catalog.theme_extractor import extract_themes_for_period
    thematic_context = extract_themes_for_period(period_slug, catalog_db)

    if thematic_context.get("top_themes"):
        print(f"  Themes: {', '.join(thematic_context['top_themes'][:5])}")
    if thematic_context.get("top_moods"):
        print(f"  Moods: {', '.join(thematic_context['top_moods'][:3])}")
    if thematic_context.get("century_breakdown"):
        century_strs = [f"{c} ({n})" for c, n in thematic_context["century_breakdown"].items()]
        print(f"  Centuries: {', '.join(century_strs)}")
    if thematic_context.get("thematic_subjects"):
        print(f"  Subject hints: {len(thematic_context['thematic_subjects'])} mapped")

    # Check research cache
    cached = db.get_cached_research(period_slug)
    if cached:
        print(f"  Using cached research ({len(cached.search_queries)} queries)")
        research = cached
    else:
        print("  Researching period art context (DeepSeek)...")
        from research.period_researcher import PeriodResearcher
        researcher = PeriodResearcher()
        research = researcher.research_period(
            period_slug, period_label, thematic_context=thematic_context
        )

        if not research:
            print("  Research failed — using fallback queries")
            from models.portfolio import PeriodResearchResult
            research = PeriodResearchResult(
                period_slug=period_slug,
                period_label=period_label,
                art_styles=["traditional painting"],
                typical_subjects=["landscape", "figures"],
                typical_media=["ink on silk", "ink on paper"],
                top_themes=thematic_context.get("top_themes", []),
                top_moods=thematic_context.get("top_moods", []),
                century_breakdown=thematic_context.get("century_breakdown", {}),
                thematic_subjects=thematic_context.get("thematic_subjects", []),
            )
        else:
            db.cache_research(research)
            print(f"  Styles: {', '.join(research.art_styles[:3])}")
            print(f"  Subjects: {', '.join(research.typical_subjects[:3])}")

    # Generate queries
    from research.query_generator import generate_queries
    queries = research.search_queries if research.search_queries else generate_queries(research)

    # Store queries back if generated fresh
    if not research.search_queries:
        research.search_queries = queries
        db.cache_research(research)

    print(f"\n  Search queries ({len(queries)}):")
    for i, q in enumerate(queries, 1):
        print(f"    {i}. {q}")

    if dry_run:
        print("\n  [DRY RUN] Stopping before download.")
        return 0

    # Search and download
    from acquisition.downloader import ArtworkDownloader
    from sources.registry import search_all_sources

    downloader = ArtworkDownloader()
    downloaded_count = 0

    for query in queries:
        if downloaded_count >= limit:
            break

        remaining = limit - downloaded_count
        print(f"\n  Searching: {query}")
        candidates = search_all_sources(query, limit_per_source=remaining)

        if not candidates:
            print("    No results")
            continue

        print(f"    Found {len(candidates)} candidates")

        for candidate in candidates:
            if downloaded_count >= limit:
                break

            result = downloader.download(candidate, period_slug, period_label)
            if result:
                db.insert_image(result)
                downloaded_count += 1
                print(f"    [{downloaded_count}/{limit}] {result.title[:60]}")

    print(f"\n  Done: {downloaded_count} images downloaded for {period_label}")
    return 0


def _curate_all(limit, dry_run, catalog_db, portfolio_db_path):
    """Curate all known dynasty periods."""
    groups = group_works_by_period(catalog_db)

    # Only curate periods with known dynasty data (skip "unspecified")
    curate_groups = [g for g in groups if g.period_slug != "unspecified"]

    print(f"\nCurating {len(curate_groups)} periods (limit {limit} images each)")
    if dry_run:
        print("[DRY RUN mode]")
    print()

    for g in curate_groups:
        _curate_period(g.period_slug, g.period_label, limit, dry_run, portfolio_db_path,
                       catalog_db=catalog_db)
        print()

    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    sys.exit(main())
