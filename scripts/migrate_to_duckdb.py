#!/usr/bin/env python3
"""
Migrate SQLite databases to DuckDB.

Uses DuckDB's built-in SQLite scanner to read existing .db files
and write them to .duckdb format.

Usage:
    python scripts/migrate_to_duckdb.py
    python scripts/migrate_to_duckdb.py --catalog-only
    python scripts/migrate_to_duckdb.py --glossary-only
    python scripts/migrate_to_duckdb.py --dry-run
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def migrate_sqlite_to_duckdb(sqlite_path: Path, duckdb_path: Path, dry_run: bool = False) -> bool:
    """
    Migrate a SQLite database to DuckDB using the built-in scanner.

    Args:
        sqlite_path: Path to source .db file
        duckdb_path: Path to target .duckdb file
        dry_run: If True, only report what would be done

    Returns:
        True if successful
    """
    import duckdb

    if not sqlite_path.exists():
        logger.error(f"Source not found: {sqlite_path}")
        return False

    logger.info(f"Migrating: {sqlite_path} -> {duckdb_path}")

    if dry_run:
        logger.info("[DRY RUN] Would migrate the following tables:")
        # Still connect to read table list
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL sqlite; LOAD sqlite;")
        conn.execute(f"ATTACH '{sqlite_path}' AS old (TYPE SQLITE)")
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' AND table_catalog = 'old'"
        ).fetchall()
        for (table,) in tables:
            count = conn.execute(f"SELECT count(*) FROM old.{table}").fetchone()[0]
            logger.info(f"  {table}: {count} rows")
        conn.close()
        return True

    # Ensure target directory exists
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing target if present
    if duckdb_path.exists():
        logger.warning(f"Target exists, will be overwritten: {duckdb_path}")
        duckdb_path.unlink()

    # Create new DuckDB and migrate
    conn = duckdb.connect(str(duckdb_path))

    try:
        conn.execute("INSTALL sqlite; LOAD sqlite;")
        conn.execute(f"ATTACH '{sqlite_path}' AS old (TYPE SQLITE)")

        # Get all tables from the SQLite database
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_catalog = 'old'"
        ).fetchall()

        if not tables:
            logger.warning("No tables found in source database")
            return False

        total_rows = 0
        for (table,) in tables:
            count = conn.execute(f"SELECT count(*) FROM old.{table}").fetchone()[0]
            conn.execute(f"CREATE TABLE {table} AS SELECT * FROM old.{table}")
            logger.info(f"  Migrated {table}: {count} rows")
            total_rows += count

        conn.execute("DETACH old")
        logger.info(f"Migration complete: {len(tables)} tables, {total_rows} total rows")

        # Verify
        for (table,) in tables:
            new_count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            logger.debug(f"  Verify {table}: {new_count} rows")

        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        # Clean up partial file
        conn.close()
        if duckdb_path.exists():
            duckdb_path.unlink()
        raise

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite databases to DuckDB")
    parser.add_argument("--catalog-only", action="store_true", help="Migrate only the catalog DB")
    parser.add_argument("--glossary-only", action="store_true", help="Migrate only the glossary DB")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be done without writing")
    parser.add_argument("--sqlite-catalog", type=Path, help="Override source catalog .db path")
    parser.add_argument("--sqlite-glossary", type=Path, help="Override source glossary .db path")
    args = parser.parse_args()

    from utils.environment_config import get_or_create_config
    env = get_or_create_config()

    success = True
    migrate_catalog = not args.glossary_only
    migrate_glossary = not args.catalog_only

    if migrate_catalog:
        sqlite_catalog = args.sqlite_catalog or env.data_root / "wuxia_catalog.db"
        duckdb_catalog = env.catalog_path  # .duckdb path from config
        if sqlite_catalog.exists():
            if not migrate_sqlite_to_duckdb(sqlite_catalog, duckdb_catalog, args.dry_run):
                success = False
        else:
            logger.warning(f"Catalog SQLite not found: {sqlite_catalog}")
            if not args.dry_run:
                success = False

    if migrate_glossary:
        sqlite_glossary = args.sqlite_glossary or env.data_root / "wuxia_glossary.db"
        # Also check project root for glossary.db
        if not sqlite_glossary.exists():
            alt = env.project_root / "glossary.db"
            if alt.exists():
                sqlite_glossary = alt
            else:
                alt2 = env.project_root / "wuxia_glossary.db"
                if alt2.exists():
                    sqlite_glossary = alt2

        duckdb_glossary = env.glossary_path
        if sqlite_glossary.exists():
            if not migrate_sqlite_to_duckdb(sqlite_glossary, duckdb_glossary, args.dry_run):
                success = False
        else:
            logger.warning(f"Glossary SQLite not found at any expected location")

    if success:
        print("\nMigration successful.")
        if not args.dry_run:
            print(f"Catalog: {env.catalog_path}")
            print(f"Glossary: {env.glossary_path}")
    else:
        print("\nMigration had errors. Check logs above.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
