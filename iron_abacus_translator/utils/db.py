#!/usr/bin/env python3
"""
Database Connection Factory

Provides DuckDB connections for the catalog and glossary databases.
Falls back to SQLite if the path ends in .db (legacy support).

Usage:
    from utils.db import connect_catalog, connect_glossary

    conn = connect_catalog()
    df = conn.execute("SELECT * FROM works LIMIT 5").fetchdf()

    conn = connect_glossary()
    rows = conn.execute("SELECT * FROM glossary").fetchall()
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _connect(path: Path):
    """
    Connect to a database file.

    Uses DuckDB for .duckdb files, SQLite for .db files.
    Supports MotherDuck URLs (md:database_name).
    """
    path_str = str(path)

    if path_str.startswith("md:"):
        # MotherDuck cloud connection
        import duckdb
        logger.debug(f"Connecting to MotherDuck: {path_str}")
        return duckdb.connect(path_str)

    if path_str.endswith(".duckdb"):
        import duckdb
        logger.debug(f"Connecting to DuckDB: {path}")
        return duckdb.connect(path_str)

    if path_str.endswith(".db"):
        # Legacy SQLite — use DuckDB's SQLite scanner for read,
        # or plain sqlite3 for write operations
        import sqlite3
        logger.debug(f"Connecting to SQLite (legacy): {path}")
        conn = sqlite3.connect(path_str)
        conn.row_factory = sqlite3.Row
        return conn

    # Default to DuckDB
    import duckdb
    logger.debug(f"Connecting to DuckDB (default): {path}")
    return duckdb.connect(path_str)


def connect_catalog(path: Optional[Path] = None):
    """
    Connect to the works catalog database.

    Args:
        path: Override path. If None, uses environment config.

    Returns:
        Database connection (DuckDB or SQLite depending on file extension).
    """
    if path is None:
        from utils.environment_config import get_or_create_config
        path = get_or_create_config().catalog_path
    return _connect(path)


def connect_glossary(path: Optional[Path] = None):
    """
    Connect to the translation glossary database.

    Args:
        path: Override path. If None, uses environment config.

    Returns:
        Database connection (DuckDB or SQLite depending on file extension).
    """
    if path is None:
        from utils.environment_config import get_or_create_config
        path = get_or_create_config().glossary_path
    return _connect(path)


def is_duckdb(conn) -> bool:
    """Check if a connection is DuckDB (vs SQLite)."""
    return type(conn).__module__.startswith("duckdb")
