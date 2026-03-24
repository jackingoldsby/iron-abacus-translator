#!/usr/bin/env python3
"""
Add 'edition' column to works table and backfill from title_chinese prefixes.

Maps:
  舊版 → Original Edition
  新修版 → Revised Edition

Also strips the edition prefix from consensus title_english if it was
appended as a suffix like "(Original Edition)".
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.db import connect_catalog

VERSION_PREFIXES = {
    "舊版": "Original Edition",
    "新修版": "Revised Edition",
}


def main():
    conn = connect_catalog()

    # Add edition column if missing
    cols = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='works'"
    ).fetchall()
    col_names = {c[0] for c in cols}

    if "edition" not in col_names:
        conn.execute("ALTER TABLE works ADD COLUMN edition VARCHAR DEFAULT ''")
        print("Added 'edition' column to works table")
    else:
        print("'edition' column already exists")

    # Backfill from title_chinese
    rows = conn.execute(
        "SELECT work_id, title_chinese, edition FROM works"
    ).fetchall()

    updated = 0
    for work_id, title_chinese, current_edition in rows:
        if current_edition:
            continue  # Already set
        for prefix_zh, prefix_en in VERSION_PREFIXES.items():
            if title_chinese and title_chinese.startswith(prefix_zh):
                conn.execute(
                    "UPDATE works SET edition = ? WHERE work_id = ?",
                    (prefix_en, work_id),
                )
                updated += 1
                print(f"  {title_chinese} -> edition='{prefix_en}'")
                break

    # Clean edition suffixes from consensus translations
    cleaned = 0
    for prefix_en in VERSION_PREFIXES.values():
        suffix = f" ({prefix_en})"
        result = conn.execute(
            """UPDATE works_consensus_translations
               SET consensus_title_english = RTRIM(REPLACE(consensus_title_english, ?, ''))
               WHERE consensus_title_english LIKE ?""",
            (suffix, f"%{suffix}"),
        )
        cleaned += result.fetchone()[0] if hasattr(result, 'fetchone') else 0

    print(f"\nBackfilled {updated} editions")
    print(f"Cleaned {cleaned} consensus title suffixes")
    conn.close()


if __name__ == "__main__":
    main()
