#!/usr/bin/env python3
"""
Apply glossary review changes from glossary_review_report.json to the CSV files.

Filters out non-changes (where current == suggested) and false-positive errors.
Applies both errors and suggestions to enrich the glossary.

Usage:
    cd iron_abacus_translator
    python scripts/apply_glossary_review.py                  # Dry run (default)
    python scripts/apply_glossary_review.py --apply          # Actually write changes
    python scripts/apply_glossary_review.py --errors-only    # Only apply severity=error
"""

import argparse
import csv
import json
import sys
from pathlib import Path

GLOSSARY_DIR = Path(__file__).parent.parent / "data" / "glossaries"
MAIN_CSV = GLOSSARY_DIR / "translation_glossary.csv"
ADDITIONS_CSV = GLOSSARY_DIR / "translation_glossary_additions.csv"
REPORT_PATH = GLOSSARY_DIR / "glossary_review_report.json"

# Map report field names to CSV column names
FIELD_TO_COLUMN = {
    "pinyin": "Pinyin",
    "recommended_form": "Recommended_Form",
    "footnote_template": "Footnote_Template",
    "translation_strategy": "Translation_Strategy",
    "category": "Category",
    "rationale": "Rationale",
}


def load_report(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]):
    # Strip None keys that csv.DictReader creates for extra fields
    clean_fieldnames = [f for f in fieldnames if f is not None]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=clean_fieldnames,
            extrasaction="ignore",
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writeheader()
        writer.writerows(rows)


def is_real_change(issue: dict) -> bool:
    """Filter out issues where current == suggested (false positives from DeepSeek)."""
    current = issue.get("current", "").strip()
    suggested = issue.get("suggested", "").strip()
    if current == suggested:
        return False
    # Also filter "missing_nuance" field — these are commentary, not editable fields
    if issue.get("field") == "missing_nuance":
        return False
    return True


def apply_issues_to_rows(rows: list[dict], issues: list[dict], errors_only: bool) -> tuple[list[dict], list[str]]:
    """Apply issues to CSV rows. Returns (modified_rows, log_lines)."""
    # Build lookup: chinese -> row index
    index = {}
    for i, row in enumerate(rows):
        index[row["Chinese"]] = i

    log = []
    applied = 0
    skipped_no_match = 0
    skipped_no_change = 0
    skipped_severity = 0

    for issue in issues:
        chinese = issue.get("chinese", "")
        field = issue.get("field", "")
        severity = issue.get("severity", "suggestion")
        suggested = issue.get("suggested", "")
        current = issue.get("current", "")

        # Skip non-real changes
        if not is_real_change(issue):
            skipped_no_change += 1
            continue

        # Skip suggestions if errors_only
        if errors_only and severity != "error":
            skipped_severity += 1
            continue

        # Map field to CSV column
        column = FIELD_TO_COLUMN.get(field)
        if not column:
            log.append(f"  SKIP {chinese} [{field}]: unknown field")
            continue

        # Find row
        if chinese not in index:
            skipped_no_match += 1
            log.append(f"  SKIP {chinese}: not found in CSV")
            continue

        row = rows[index[chinese]]
        old_value = row.get(column, "")

        # Verify current matches (loosely — DeepSeek may truncate)
        # Just apply the suggested value
        row[column] = suggested
        applied += 1

        # Truncate for display
        old_display = old_value[:60] + "..." if len(old_value) > 60 else old_value
        new_display = suggested[:60] + "..." if len(suggested) > 60 else suggested
        log.append(f"  [{severity.upper()}] {chinese}.{column}: {old_display!r} → {new_display!r}")

    log.insert(0, f"\nApplied: {applied}, Skipped: no-change={skipped_no_change}, severity={skipped_severity}, no-match={skipped_no_match}")
    return rows, log


def main():
    parser = argparse.ArgumentParser(description="Apply glossary review changes")
    parser.add_argument("--apply", action="store_true", help="Actually write changes (default: dry run)")
    parser.add_argument("--errors-only", action="store_true", help="Only apply severity=error")
    parser.add_argument("--report", type=str, default=None, help="Path to review report JSON")
    args = parser.parse_args()

    report_path = Path(args.report) if args.report else REPORT_PATH
    if not report_path.exists():
        print(f"Report not found: {report_path}")
        return 1

    report = load_report(report_path)
    issues = report.get("issues", [])
    print(f"Loaded {len(issues)} issues from report")

    # Process each CSV
    for csv_path in [MAIN_CSV, ADDITIONS_CSV]:
        if not csv_path.exists():
            continue
        rows = load_csv(csv_path)
        if not rows:
            continue

        fieldnames = list(rows[0].keys())
        print(f"\n=== {csv_path.name} ({len(rows)} entries) ===")

        modified_rows, log = apply_issues_to_rows(rows, issues, args.errors_only)
        for line in log:
            print(line)

        if args.apply:
            write_csv(csv_path, modified_rows, fieldnames)
            print(f"  Written to {csv_path}")
        else:
            print(f"  DRY RUN — use --apply to write changes")

    return 0


if __name__ == "__main__":
    sys.exit(main())
