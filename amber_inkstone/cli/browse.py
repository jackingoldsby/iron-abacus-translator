#!/usr/bin/env python3
"""
CLI: browse — browse the artwork portfolio.

Usage:
    python -m cli.browse
    python -m cli.browse --period "Ming Dynasty"
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from catalog.portfolio_db import PortfolioDB
from config.dynasty_periods import normalize_period, DYNASTY_PERIODS


def main():
    parser = argparse.ArgumentParser(
        description="Amber Inkstone — Browse artwork portfolio"
    )
    parser.add_argument(
        "--period", type=str,
        help="Filter by period (e.g. 'Ming Dynasty')",
    )
    parser.add_argument(
        "--portfolio-db", type=Path,
        help="Override portfolio DB path",
    )

    args = parser.parse_args()
    db = PortfolioDB(args.portfolio_db)

    if args.period:
        slug, label = normalize_period(args.period)
        if slug == "unspecified":
            for s, (l, _, _) in DYNASTY_PERIODS.items():
                if l.lower() == args.period.lower():
                    slug, label = s, l
                    break
        images = db.get_images_by_period(slug)
        print(f"\n{label} — {len(images)} images\n")
    else:
        images = db.get_all_images()
        print(f"\nAll periods — {len(images)} images\n")

    if not images:
        print("No images in portfolio. Run 'python -m cli.curate' to build.")
        return 0

    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(show_lines=False)
        table.add_column("ID", style="dim", max_width=12)
        table.add_column("Period", max_width=18)
        table.add_column("Title", max_width=40)
        table.add_column("Artist", max_width=20)
        table.add_column("Source", max_width=12)
        table.add_column("Size", justify="right", max_width=10)

        for img in images:
            size = f"{img.width}x{img.height}" if img.width else "?"
            table.add_row(
                img.image_id[:12],
                img.period_label,
                img.title[:40] if img.title else "-",
                img.artist[:20] if img.artist else "-",
                img.source_api.replace("_", " "),
                size,
            )

        console.print(table)

    except ImportError:
        # Fallback without rich
        print(f"{'ID':<14} {'Period':<18} {'Title':<40} {'Source':<12}")
        print("-" * 86)
        for img in images:
            print(
                f"{img.image_id[:12]:<14} "
                f"{img.period_label:<18} "
                f"{(img.title or '-')[:38]:<40} "
                f"{img.source_api:<12}"
            )

    print()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
