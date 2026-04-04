"""Find works needing scraping from the DuckDB catalog."""

import logging
from typing import Dict, List

import duckdb

from config.defaults import DEFAULT_DB_PATH

logger = logging.getLogger(__name__)


def get_works_needing_scraping(db_path: str = DEFAULT_DB_PATH) -> List[Dict]:
    """Find catalog works that have no work_files (i.e., need scraping).

    Returns works with A-prefix numbers that have no associated files.
    """
    con = duckdb.connect(db_path, read_only=True)
    rows = con.execute("""
        SELECT w.work_id, w.work_number, w.title_chinese, w.author_chinese,
               w.directory_number, w.work_link
        FROM works w
        LEFT JOIN work_files wf ON w.work_id = wf.work_id
        WHERE w.work_number LIKE 'A%'
          AND wf.file_id IS NULL
        ORDER BY w.work_number
    """).fetchall()
    con.close()

    return [
        {
            "work_id": r[0],
            "work_number": r[1],
            "title_chinese": r[2],
            "author_chinese": r[3],
            "directory_number": r[4],
            "work_link": r[5],
        }
        for r in rows
    ]


def get_work_info(db_path: str, work_number: str) -> Dict | None:
    """Get info for a specific work by number."""
    con = duckdb.connect(db_path, read_only=True)
    row = con.execute(
        """SELECT work_id, work_number, title_chinese, author_chinese,
                  directory_number, work_link
           FROM works WHERE work_number = ?""",
        [work_number],
    ).fetchone()
    con.close()

    if not row:
        return None
    return {
        "work_id": row[0],
        "work_number": row[1],
        "title_chinese": row[2],
        "author_chinese": row[3],
        "directory_number": row[4],
        "work_link": row[5],
    }


def get_scrape_status(db_path: str = DEFAULT_DB_PATH) -> List[Dict]:
    """Get scraping status for all A-prefix works."""
    con = duckdb.connect(db_path, read_only=True)
    rows = con.execute("""
        SELECT w.work_number, w.title_chinese, w.author_chinese,
               w.work_link,
               COUNT(wf.file_id) as file_count,
               SUM(COALESCE(wf.character_count, 0)) as total_chars
        FROM works w
        LEFT JOIN work_files wf ON w.work_id = wf.work_id
        WHERE w.work_number LIKE 'A%'
        GROUP BY w.work_number, w.title_chinese, w.author_chinese, w.work_link
        ORDER BY w.work_number
    """).fetchall()
    con.close()

    return [
        {
            "work_number": r[0],
            "title": r[1],
            "author": r[2],
            "work_link": r[3],
            "files": r[4],
            "characters": r[5],
        }
        for r in rows
    ]
