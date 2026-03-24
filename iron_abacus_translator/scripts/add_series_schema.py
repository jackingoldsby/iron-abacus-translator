#!/usr/bin/env python3
"""
Add series, author metadata, and URL tables to the catalog database.

Creates:
- authors table (with Wikipedia URLs, birth/death years)
- series table (series groupings like Condor Trilogy, Tianshan series)
- work_series table (maps works to their series with ordering)
- work_urls table (Wikipedia and other reference URLs per work)
"""

from utils.db import connect_catalog
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.environment_config import get_or_create_config
CATALOG_DB = get_or_create_config().catalog_path


def migrate(db_path=CATALOG_DB):
    conn = connect_catalog(db_path)
    cur = conn.cursor()

    # Authors table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS authors (
            author_id INTEGER PRIMARY KEY,
            name_chinese TEXT NOT NULL UNIQUE,
            name_english TEXT,
            pen_name_chinese TEXT,
            real_name_chinese TEXT,
            birth_year INTEGER,
            death_year INTEGER,
            nationality TEXT,
            wikipedia_url TEXT,
            description TEXT
        )
    """)

    # Series table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS series (
            series_id INTEGER PRIMARY KEY,
            name_chinese TEXT,
            name_english TEXT NOT NULL,
            author_chinese TEXT NOT NULL,
            series_type TEXT DEFAULT 'series',  -- series, trilogy, duology, standalone_group
            description TEXT,
            historical_period TEXT,
            wikipedia_url TEXT,
            UNIQUE(name_english, author_chinese)
        )
    """)

    # Work-Series mapping (a work can belong to multiple series)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS work_series (
            work_id INTEGER NOT NULL,
            series_id INTEGER NOT NULL,
            order_in_series INTEGER,
            PRIMARY KEY (work_id, series_id),
            FOREIGN KEY (work_id) REFERENCES works(work_id),
            FOREIGN KEY (series_id) REFERENCES series(series_id)
        )
    """)

    # Work URLs (multiple URLs per work)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS work_urls (
            url_id INTEGER PRIMARY KEY,
            work_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            url_type TEXT DEFAULT 'wikipedia',  -- wikipedia, goodreads, imdb, etc.
            description TEXT,
            FOREIGN KEY (work_id) REFERENCES works(work_id),
            UNIQUE(work_id, url)
        )
    """)

    conn.commit()
    print("Schema migration complete.")

    # Show table counts
    for table in ['authors', 'series', 'work_series', 'work_urls']:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"  {table}: {cur.fetchone()[0]} rows")

    conn.close()


if __name__ == "__main__":
    migrate()
