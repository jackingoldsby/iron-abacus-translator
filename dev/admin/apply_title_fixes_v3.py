#!/usr/bin/env python3
"""
Apply non-stylistic title fixes from DeepSeek review (round 3).
Categories: canonical, mistranslation, pinyin_left, grammar, series_format.
Skips purely stylistic changes.

Usage:
    python dev/admin/apply_title_fixes_v3.py --dry-run
    python dev/admin/apply_title_fixes_v3.py
"""

import csv
import duckdb
import sys
from pathlib import Path

DB_PATH = Path.home() / "project_files" / "translation_project" / "db" / "works_translator.duckdb"
REVIEW_TSV = Path("/tmp/title_review.tsv")


def categorize(reason: str) -> str:
    r = reason.lower()
    if "canonical" in r or "established" in r or "published" in r:
        return "canonical"
    elif "untranslat" in r or "pinyin" in r or "transliterat" in r:
        return "pinyin_left"
    elif "mistranslat" in r or "incorrect" in r or "wrong" in r or "nonsensical" in r or "misinterpret" in r:
        return "mistranslation"
    elif "ungrammatical" in r or "awkward" in r or "clumsy" in r or "unidiomatic" in r:
        return "grammar"
    elif "volume" in r or "series" in r or "consistent" in r:
        return "series_format"
    else:
        return "stylistic"


def main():
    dry_run = "--dry-run" in sys.argv

    with open(REVIEW_TSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)

    # Filter to non-stylistic
    accept_categories = {"canonical", "mistranslation", "pinyin_left", "grammar", "series_format"}
    fixes = []
    skipped_stylistic = 0
    for r in rows:
        cat = categorize(r.get("reason", ""))
        if cat in accept_categories:
            fixes.append({
                "work_number": r["work_number"],
                "current": r["current_english"],
                "suggested": r["suggested_english"],
                "category": cat,
                "reason": r.get("reason", ""),
            })
        else:
            skipped_stylistic += 1

    print(f"Total suggestions: {len(rows)}")
    print(f"Skipping stylistic: {skipped_stylistic}")
    print(f"Applying: {len(fixes)}\n")

    con = duckdb.connect(str(DB_PATH))
    updated = 0
    not_found = 0
    already_changed = 0

    for fix in sorted(fixes, key=lambda x: x["work_number"]):
        row = con.execute(
            "SELECT work_id, title_english FROM works WHERE work_number = ?",
            [fix["work_number"]]
        ).fetchone()

        if not row:
            print(f"  SKIP (not found): {fix['work_number']}")
            not_found += 1
            continue

        work_id, current_title = row

        # Only update if current title still matches what the review saw
        if current_title != fix["current"]:
            # Already changed by a prior fix script
            already_changed += 1
            continue

        if current_title == fix["suggested"]:
            continue

        if dry_run:
            print(f"  [{fix['category']}] {fix['work_number']}: {current_title!r} -> {fix['suggested']!r}")
        else:
            con.execute("UPDATE works SET title_english = ? WHERE work_id = ?", [fix["suggested"], work_id])
            print(f"  [{fix['category']}] {fix['work_number']}: {current_title!r} -> {fix['suggested']!r}")
        updated += 1

    con.close()

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Updated: {updated}, Not found: {not_found}, Already changed: {already_changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
