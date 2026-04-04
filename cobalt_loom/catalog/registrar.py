"""Update catalog entries for scraped works."""

import logging
from pathlib import Path

import duckdb

from config.defaults import DEFAULT_DB_PATH

logger = logging.getLogger(__name__)


def update_work_link(db_path: str, work_number: str, source_url: str):
    """Update the work_link column for a scraped work."""
    con = duckdb.connect(db_path)
    con.execute(
        "UPDATE works SET work_link = ? WHERE work_number = ?",
        [source_url, work_number],
    )
    con.commit()
    con.close()
    logger.info(f"Updated work_link for {work_number}: {source_url}")


def register_work_file(
    db_path: str,
    work_number: str,
    filename: str,
    full_path: str,
    directory_name: str,
    character_count: int,
    volume: str = "",
):
    """Create a work_files entry for the scraped JSON output."""
    con = duckdb.connect(db_path)

    # Get work_id
    row = con.execute(
        "SELECT work_id FROM works WHERE work_number = ?",
        [work_number],
    ).fetchone()
    if not row:
        con.close()
        raise ValueError(f"Work {work_number} not found in catalog")
    work_id = row[0]

    # Check for existing entry
    existing = con.execute(
        "SELECT file_id FROM work_files WHERE work_id = ? AND filename = ?",
        [work_id, filename],
    ).fetchone()
    if existing:
        # Update character count
        con.execute(
            "UPDATE work_files SET character_count = ?, full_path = ? WHERE file_id = ?",
            [character_count, full_path, existing[0]],
        )
        con.commit()
        con.close()
        logger.info(f"Updated existing work_file for {work_number}: {filename}")
        return

    # Get next file_id
    max_id = con.execute("SELECT COALESCE(MAX(file_id), 0) FROM work_files").fetchone()[0]
    next_id = max_id + 1

    con.execute(
        """INSERT INTO work_files (file_id, work_id, volume, filename, full_path,
           directory_name, character_count)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [next_id, work_id, volume, filename, full_path, directory_name, character_count],
    )
    con.commit()
    con.close()
    logger.info(f"Registered work_file for {work_number}: {filename}")
