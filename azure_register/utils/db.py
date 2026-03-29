#!/usr/bin/env python3
"""
Database connection for Azure Register.

Thin wrapper — connects to works_translator.duckdb.
"""

import logging
from pathlib import Path
from typing import Optional

import duckdb

from azure_register.config.defaults import DEFAULT_DB_PATH

logger = logging.getLogger(__name__)


def connect_catalog(path: Optional[str] = None) -> duckdb.DuckDBPyConnection:
    """Connect to the works catalog database.

    Args:
        path: Explicit path to DuckDB file. If None, uses DEFAULT_DB_PATH.

    Returns:
        DuckDB connection.
    """
    db_path = Path(path) if path else DEFAULT_DB_PATH
    logger.debug(f"Connecting to catalog: {db_path}")
    return duckdb.connect(str(db_path))
