#!/usr/bin/env python3
"""
Reign Period Lookup & Historical Reference Cache CLI

Query Chinese reign periods, convert reign year references to CE dates,
and manage the incremental Wikipedia-backed historical reference cache.

Usage:
    cd iron_abacus_translator

    # Reign period lookups
    python -m cli.reign --query "康熙十四年"
    python -m cli.reign --reign "康熙"
    python -m cli.reign --dynasty "清"
    python -m cli.reign --stats

    # Historical reference cache
    python -m cli.reign --ref "御史台" --wiki "Censorate" --category institution
    python -m cli.reign --ref "御史台"                  # cache-only lookup
    python -m cli.reign --ref-search "censor"            # search cached terms
    python -m cli.reign --ref-stats                      # show cache stats
"""

import argparse
import sys
from pathlib import Path

# Resolve imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.reign_lookup import ReignLookup


def _handle_reign_commands(args, lookup):
    """Handle reign period lookup commands."""
    if args.query:
        result = lookup.convert(args.query)
        if result:
            print(result)
        else:
            print(f"Could not convert: {args.query}")
            # Try partial match — maybe it's just a reign name
            info = lookup.lookup_reign(args.query)
            if info:
                print(f"  Found reign: {info['reign_name_en']} ({info['start_year']}–{info['end_year']}), {info['dynasty_en']}")
            return 1

    if args.reign:
        info = lookup.lookup_reign(args.reign)
        if info:
            print(f"Reign:    {info['reign_name_zh']} ({info['reign_name_py']})")
            print(f"English:  {info['reign_name_en']}")
            print(f"Dynasty:  {info['dynasty']} ({info['dynasty_en']})")
            print(f"Years:    {info['start_year']}–{info['end_year']}")
            if info.get('emperor_zh'):
                print(f"Emperor:  {info['emperor_zh']} ({info['emperor_py']})")
                if info.get('emperor_en'):
                    print(f"          {info['emperor_en']}")
            if info.get('notes'):
                print(f"Notes:    {info['notes'][:200]}{'...' if len(info.get('notes', '')) > 200 else ''}")
            if info.get('wiki_url'):
                print(f"Wiki:     {info['wiki_url']}")
        else:
            print(f"Reign period not found: {args.reign}")
            return 1

    if args.dynasty:
        periods = lookup.lookup_dynasty(args.dynasty)
        if periods:
            print(f"{periods[0]['dynasty_en']} ({args.dynasty}) — {len(periods)} reign periods:\n")
            for p in periods:
                emperor = p.get('emperor_en', p.get('emperor_zh', ''))
                print(f"  {p['reign_name_zh']} ({p['reign_name_py']:<16s}) {p['start_year']:>5}–{p['end_year']:<5}  {emperor}")
        else:
            print(f"No reign periods found for dynasty: {args.dynasty}")
            return 1

    if args.stats:
        print(f"Loaded {lookup.reign_count} reign periods across {len(lookup.dynasty_names)} dynasties:")
        for dynasty_zh in lookup.dynasty_names:
            periods = lookup.lookup_dynasty(dynasty_zh)
            if periods:
                print(f"  {periods[0]['dynasty_en']}: {len(periods)} periods ({periods[0]['start_year']}–{periods[-1]['end_year']})")

    return 0


def _handle_ref_commands(args):
    """Handle historical reference cache commands."""
    from utils.historical_ref_cache import HistoricalRefCache, CATEGORIES

    cache = HistoricalRefCache(db_path=args.db)

    if args.ref:
        if args.wiki:
            # Fetch and cache
            category = args.category or "other"
            if category not in CATEGORIES:
                print(f"Invalid category: {category}")
                print(f"Valid categories: {', '.join(CATEGORIES.keys())}")
                return 1

            entry = cache.get_or_fetch(
                term_zh=args.ref,
                wiki_title=args.wiki,
                category=category,
            )
            if entry:
                print(f"Term:     {entry['term_zh']}")
                print(f"English:  {entry['term_en']}")
                print(f"Category: {entry['category']}")
                print(f"Wiki:     {entry.get('wiki_url', 'N/A')}")
                print(f"Summary:  {entry['summary'][:300]}{'...' if len(entry.get('summary', '')) > 300 else ''}")
            else:
                print(f"Failed to fetch Wikipedia article: {args.wiki}")
                return 1
        else:
            # Cache-only lookup
            entry = cache.get(args.ref)
            if entry:
                print(f"Term:     {entry['term_zh']}")
                print(f"English:  {entry['term_en']}")
                print(f"Category: {entry['category']}")
                print(f"Wiki:     {entry.get('wiki_url', 'N/A')}")
                summary = entry.get('summary', '')
                print(f"Summary:  {summary[:300]}{'...' if len(summary) > 300 else ''}")
                if entry.get('fetch_failed'):
                    print("  (previous fetch failed)")
            else:
                print(f"Not cached: {args.ref}")
                print("  Use --wiki <article_title> to fetch from Wikipedia")
                return 1

    if args.ref_search:
        results = cache.search(args.ref_search)
        if results:
            print(f"Found {len(results)} matching term(s):\n")
            for entry in results:
                summary_preview = (entry.get('summary', '') or '')[:80]
                print(f"  {entry['term_zh']}  {entry['term_en']:<25s}  [{entry['category']}]  {summary_preview}...")
        else:
            print(f"No cached terms matching: {args.ref_search}")
            return 1

    if args.ref_stats:
        st = cache.stats()
        print(f"Historical Reference Cache: {st['total']} terms cached")
        if st['by_category']:
            print("\nBy category:")
            for cat, count in sorted(st['by_category'].items(), key=lambda x: -x[1]):
                desc = CATEGORIES.get(cat, "")
                print(f"  {cat:<15s}  {count:>4d}  {desc}")
        if st['fetch_failed']:
            print(f"\nFetch failures: {st['fetch_failed']}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Chinese reign period lookup & historical reference cache"
    )

    # Reign period commands
    reign_group = parser.add_argument_group("Reign Period Lookup")
    reign_group.add_argument("--query", "-q", help="Convert reign year to CE date (e.g. '康熙十四年')")
    reign_group.add_argument("--reign", "-r", help="Look up a reign period by Chinese name (e.g. '康熙')")
    reign_group.add_argument("--dynasty", "-d", help="List all reign periods for a dynasty (e.g. '清')")
    reign_group.add_argument("--stats", action="store_true", help="Show loaded reign period stats")

    # Historical reference cache commands
    ref_group = parser.add_argument_group("Historical Reference Cache")
    ref_group.add_argument("--ref", help="Look up or cache a historical term (Chinese)")
    ref_group.add_argument("--wiki", help="Wikipedia article title for --ref (triggers fetch)")
    ref_group.add_argument("--category", help="Category for --ref (institution, title, place, event, concept, text, practice, other)")
    ref_group.add_argument("--ref-search", help="Search cached terms by keyword")
    ref_group.add_argument("--ref-stats", action="store_true", help="Show cache statistics")

    # Shared
    parser.add_argument("--db", type=Path, help="DuckDB path override")

    args = parser.parse_args()

    has_reign = any([args.query, args.reign, args.dynasty, args.stats])
    has_ref = any([args.ref, args.ref_search, args.ref_stats])

    if not has_reign and not has_ref:
        parser.print_help()
        return 1

    rc = 0

    if has_reign:
        lookup = ReignLookup(db_path=args.db)
        rc = _handle_reign_commands(args, lookup)
        if rc != 0:
            return rc

    if has_ref:
        rc = _handle_ref_commands(args)

    return rc


if __name__ == "__main__":
    sys.exit(main())
