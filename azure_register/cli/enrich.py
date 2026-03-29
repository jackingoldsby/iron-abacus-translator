#!/usr/bin/env python3
"""
Unified CLI for Azure Register catalog enrichment.

Usage:
    python -m cli.enrich library --dry-run
    python -m cli.enrich library --limit 5 --diff
    python -m cli.enrich library --author "Jin Yong" --unenriched-only

    python -m cli.enrich reader --dry-run
    python -m cli.enrich reader --limit 10 --diff

    python -m cli.enrich csv --csv /path/to/works.csv

    python -m cli.enrich status
"""

import argparse
import logging
import sys
from pathlib import Path

from azure_register.config.defaults import (
    DEFAULT_DB_PATH,
    DEFAULT_WORKERS,
    LIBRARY_BATCH_SIZE,
    READER_BATCH_SIZE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def add_shared_args(parser: argparse.ArgumentParser):
    """Add arguments shared across subcommands."""
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB_PATH),
                        help="Path to DuckDB database")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show proposed changes without writing")
    parser.add_argument("--diff", action="store_true",
                        help="Show before/after diff")


def add_llm_args(parser: argparse.ArgumentParser, default_batch: int):
    """Add LLM-specific arguments."""
    parser.add_argument("--limit", type=int, help="Process only first N works")
    parser.add_argument("--author", help="Filter by author name (English)")
    parser.add_argument("--unenriched-only", action="store_true",
                        help="Only process unenriched works")
    parser.add_argument("--batch-size", type=int, default=default_batch,
                        help=f"Works per API call (default: {default_batch})")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"Parallel API workers (default: {DEFAULT_WORKERS})")


def cmd_library(args):
    """Run library (factual) enrichment."""
    _load_dotenv()
    _check_db(args.db)

    from azure_register.enrichers.library import LibraryEnricher

    enricher = LibraryEnricher(
        db_path=args.db,
        workers=args.workers,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        diff=args.diff,
    )
    enricher.enrich(
        author_filter=args.author,
        unenriched_only=args.unenriched_only,
        limit=args.limit,
        sync_status=getattr(args, "sync_status", False),
    )


def cmd_reader(args):
    """Run reader (subjective) enrichment."""
    _load_dotenv()
    _check_db(args.db)

    from azure_register.enrichers.reader import ReaderEnricher

    enricher = ReaderEnricher(
        db_path=args.db,
        workers=args.workers,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        diff=args.diff,
    )
    enricher.enrich(
        author_filter=args.author,
        unenriched_only=args.unenriched_only,
        limit=args.limit,
    )


def cmd_csv(args):
    """Run CSV import."""
    _check_db(args.db)

    from azure_register.enrichers.csv_loader import CsvEnricher

    enricher = CsvEnricher(db_path=args.db)
    enricher.load(args.csv, dry_run=args.dry_run)


def cmd_status(args):
    """Show enrichment status."""
    _check_db(args.db)

    from azure_register.utils.db import connect_catalog

    con = connect_catalog(args.db)
    try:
        total = con.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        lib_enriched = con.execute(
            "SELECT COUNT(*) FROM works WHERE enriched_at IS NOT NULL"
        ).fetchone()[0]
        reader_enriched = con.execute(
            "SELECT COUNT(*) FROM works WHERE reader_enriched_at IS NOT NULL"
        ).fetchone()[0]
        has_summary = con.execute(
            "SELECT COUNT(*) FROM works WHERE summary IS NOT NULL AND summary != ''"
        ).fetchone()[0]
        has_rating = con.execute(
            "SELECT COUNT(*) FROM works WHERE rating_tier IS NOT NULL"
        ).fetchone()[0]

        print(f"\nCatalog Enrichment Status")
        print(f"{'=' * 40}")
        print(f"  Total works:           {total}")
        print(f"  Library enriched:      {lib_enriched}/{total}")
        print(f"  Reader enriched:       {reader_enriched}/{total}")
        print(f"  With summary:          {has_summary}/{total}")
        print(f"  With rating_tier:      {has_rating}/{total}")
        print(f"{'=' * 40}")

        if has_rating:
            print("\n  Rating tier distribution:")
            rows = con.execute("""
                SELECT rating_tier, COUNT(*) as cnt
                FROM works WHERE rating_tier IS NOT NULL
                GROUP BY rating_tier ORDER BY cnt DESC
            """).fetchall()
            for tier, cnt in rows:
                print(f"    {tier}: {cnt}")
    finally:
        con.close()


def _load_dotenv():
    """Load .env for API keys."""
    try:
        from dotenv import load_dotenv

        for env_path in [
            Path(__file__).resolve().parent.parent / ".env",
            Path(__file__).resolve().parent.parent.parent / ".env",
            Path(__file__).resolve().parent.parent.parent / "iron_abacus_translator" / ".env",
        ]:
            if env_path.exists():
                load_dotenv(env_path)
                break
        else:
            load_dotenv()
    except ImportError:
        pass


def _check_db(db_path: str):
    """Verify database exists."""
    if not Path(db_path).exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Azure Register -- Works Catalog Enrichment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # library subcommand
    p_lib = subparsers.add_parser("library", help="Factual metadata enrichment via DeepSeek")
    add_shared_args(p_lib)
    add_llm_args(p_lib, LIBRARY_BATCH_SIZE)
    p_lib.add_argument("--sync-status", action="store_true",
                       help="Sync enriched fields back to status.json files")
    p_lib.set_defaults(func=cmd_library)

    # reader subcommand
    p_reader = subparsers.add_parser("reader", help="Reader-oriented metadata via DeepSeek")
    add_shared_args(p_reader)
    add_llm_args(p_reader, READER_BATCH_SIZE)
    p_reader.set_defaults(func=cmd_reader)

    # csv subcommand
    p_csv = subparsers.add_parser("csv", help="Import metadata from CSV")
    add_shared_args(p_csv)
    p_csv.add_argument("--csv", required=True, help="Path to works.csv file")
    p_csv.set_defaults(func=cmd_csv)

    # status subcommand
    p_status = subparsers.add_parser("status", help="Show enrichment status")
    p_status.add_argument("--db", type=str, default=str(DEFAULT_DB_PATH),
                          help="Path to DuckDB database")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
