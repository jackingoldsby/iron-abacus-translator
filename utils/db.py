#!/usr/bin/env python3
"""
Database Connection Factory

Provides DuckDB connections for the catalog and glossary databases.

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

import duckdb

logger = logging.getLogger(__name__)


def _connect(path: Path, read_only: bool = False):
    """
    Connect to a DuckDB database file.

    Supports MotherDuck URLs (md:database_name).
    """
    path_str = str(path)

    if path_str.startswith("md:"):
        logger.debug(f"Connecting to MotherDuck: {path_str}")
        return duckdb.connect(path_str)

    logger.debug(f"Connecting to DuckDB: {path}")
    return duckdb.connect(path_str, read_only=read_only)


def connect_catalog(path: Optional[Path] = None, read_only: bool = False):
    """
    Connect to the works catalog database.

    Args:
        path: Override path. If None, uses environment config.
        read_only: Open in read-only mode.

    Returns:
        DuckDB connection.
    """
    if path is None:
        from utils.environment_config import get_or_create_config
        path = get_or_create_config().catalog_path
    return _connect(path, read_only=read_only)


def connect_glossary(path: Optional[Path] = None, read_only: bool = False):
    """
    Connect to the translation glossary database.

    Args:
        path: Override path. If None, uses environment config.
        read_only: Open in read-only mode.

    Returns:
        DuckDB connection.
    """
    if path is None:
        from utils.environment_config import get_or_create_config
        path = get_or_create_config().glossary_path
    return _connect(path, read_only=read_only)
