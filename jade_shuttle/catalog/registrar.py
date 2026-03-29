"""Work registration — assign numbers and write to DuckDB catalog."""

import logging
from pathlib import Path
from typing import List

import duckdb

from config.defaults import VOLUME_LETTERS
from models.core import WorkGroup

logger = logging.getLogger(__name__)


def get_next_work_number(db_path: str) -> int:
    """Get the next A-prefix work number."""
    con = duckdb.connect(db_path, read_only=True)
    result = con.execute(
        "SELECT MAX(CAST(SUBSTR(work_number, 2) AS INTEGER)) "
        "FROM works WHERE work_number LIKE 'A%' AND work_number NOT LIKE 'A%[a-z]'"
    ).fetchone()
    con.close()
    max_num = result[0] if result and result[0] else 0
    return max_num + 1


def get_next_directory_number(output_dir: str) -> int:
    """Get the next work_XXXX directory number."""
    max_num = 0
    base = Path(output_dir)
    if base.exists():
        for d in base.iterdir():
            if not d.is_dir():
                continue
            if d.name.startswith("work_"):
                try:
                    num = int(d.name[len("work_"):])
                    max_num = max(max_num, num)
                except ValueError:
                    pass
    return max_num + 1


def register_works(
    db_path: str,
    work_groups: List[WorkGroup],
    output_dir: str,
    dry_run: bool = False,
):
    """Register new works in the DuckDB catalog."""
    if dry_run:
        return

    con = duckdb.connect(db_path)

    max_work_id = con.execute("SELECT COALESCE(MAX(work_id), 0) FROM works").fetchone()[0]
    max_file_id = con.execute("SELECT COALESCE(MAX(file_id), 0) FROM work_files").fetchone()[0]
    max_author_id = con.execute("SELECT COALESCE(MAX(author_id), 0) FROM authors").fetchone()[0]

    next_work_id = max_work_id + 1
    next_file_id = max_file_id + 1
    next_author_id = max_author_id + 1

    for group in work_groups:
        if group.is_duplicate:
            continue

        # Ensure author exists
        author_row = con.execute(
            "SELECT author_id FROM authors WHERE name_chinese = ?",
            [group.author_trad],
        ).fetchone()

        if not author_row:
            author_row = con.execute(
                "SELECT author_id FROM authors WHERE name_chinese = ?",
                [group.author_simp],
            ).fetchone()

        if not author_row:
            con.execute(
                "INSERT INTO authors (author_id, name_chinese) VALUES (?, ?)",
                [next_author_id, group.author_trad],
            )
            logger.info(f"  Created author: {group.author_trad}")
            next_author_id += 1

        # Insert work
        work_id = next_work_id
        next_work_id += 1
        con.execute(
            """INSERT INTO works (work_id, work_number, title_chinese, author_chinese,
               directory_number, title_author, edition)
               VALUES (?, ?, ?, ?, ?, ?, 'annas_archive')""",
            [
                work_id,
                group.work_number,
                group.base_title_trad,
                group.author_trad,
                group.directory_number,
                f"{group.base_title_trad}_{group.author_trad}",
            ],
        )

        # Insert work_files for each volume
        for i, vol in enumerate(group.volumes):
            vol_letter = VOLUME_LETTERS[i] if len(group.volumes) > 1 else ""
            wn = f"{group.work_number}{vol_letter}"
            filename = f"{wn}_{vol.title_traditional}_{vol.author_traditional}.json"
            dir_name = f"work_{group.directory_number}"
            full_path = str(Path(output_dir) / dir_name / filename)

            con.execute(
                """INSERT INTO work_files (file_id, work_id, volume, filename, full_path,
                   directory_name, character_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [next_file_id, work_id, vol_letter, filename, full_path, dir_name, vol.character_count],
            )
            next_file_id += 1

    con.close()
