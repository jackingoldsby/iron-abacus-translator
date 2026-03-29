#!/usr/bin/env python3
"""
DEPRECATED: Use azure_register instead:
    cd azure_register && python -m cli.enrich library --dry-run

Library Metadata Enrichment via DeepSeek → DuckDB

Validates and enriches library metadata using DeepSeek as a peer sinologist.
Reads from and writes to the canonical DuckDB database (works_translator.duckdb).

Enriched fields:
    works: publication_year, publication_note, setting_period, summary, category_english, enriched_at
    authors: birth_year, death_year, pen_name_origin, wikipedia_url

Usage:
    python dev/admin/enrich_library_metadata.py --limit 5 --dry-run
    python dev/admin/enrich_library_metadata.py --limit 5 --diff
    python dev/admin/enrich_library_metadata.py --unenriched-only --diff
    python dev/admin/enrich_library_metadata.py --author "Jin Yong" --diff
    python dev/admin/enrich_library_metadata.py --sync-status   # Also update status.json files
"""

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

# Resolve project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent / "iron_abacus_translator"
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = Path.home() / "project_files" / "translation_project" / "db" / "works_translator.duckdb"
LIBRARY_ROOT = Path.home() / "project_files" / "translation_project" / "library"

BATCH_SIZE = 15

# Columns that must never be overwritten by enrichment
PROTECTED_WORK_FIELDS = {"work_id", "work_number", "work_link", "library_path", "created_at", "title_author", "directory_number", "edition"}


def migrate_schema(con: duckdb.DuckDBPyConnection):
    """Add missing columns to works and authors tables."""
    migrations = [
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS setting_period VARCHAR",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS publication_note VARCHAR",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS enriched_at TIMESTAMP",
        "ALTER TABLE authors ADD COLUMN IF NOT EXISTS pen_name_origin VARCHAR",
        # Reader-oriented enrichment columns
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS rating_tier VARCHAR",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS rating_note VARCHAR",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS writing_style VARCHAR",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS themes VARCHAR",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS mood VARCHAR",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS comparable_works VARCHAR",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS wuxia_era VARCHAR",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS reader_enriched_at TIMESTAMP",
        "ALTER TABLE authors ADD COLUMN IF NOT EXISTS writing_style VARCHAR",
        "ALTER TABLE authors ADD COLUMN IF NOT EXISTS best_known_for VARCHAR",
    ]
    for sql in migrations:
        try:
            con.execute(sql)
        except duckdb.CatalogException:
            # Column already exists (older DuckDB without IF NOT EXISTS support)
            pass
    logger.info("Schema migration complete")


def load_works(con: duckdb.DuckDBPyConnection, author_filter: str = None,
               unenriched_only: bool = False, limit: int = None) -> list[dict]:
    """Load works from DuckDB with optional filtering."""
    query = """
        SELECT
            w.work_id,
            w.work_number,
            w.title_chinese,
            w.title_english,
            w.author_chinese,
            w.author_english,
            w.work_link,
            w.publication_year,
            w.summary,
            w.category_english,
            w.setting_period,
            w.publication_note,
            w.enriched_at,
            w.library_path,
            a.name_english AS author_name_english,
            a.birth_year AS author_birth_year,
            a.death_year AS author_death_year,
            a.wikipedia_url AS author_wikipedia_url,
            a.pen_name_origin AS author_pen_name_origin
        FROM works w
        LEFT JOIN authors a ON w.author_chinese = a.name_chinese
        WHERE 1=1
    """
    params = []

    if author_filter:
        query += " AND LOWER(w.author_english) LIKE ?"
        params.append(f"%{author_filter.lower()}%")

    if unenriched_only:
        query += " AND w.enriched_at IS NULL"

    query += " ORDER BY w.work_number"

    if limit:
        query += f" LIMIT {limit}"

    rows = con.execute(query, params).fetchall()
    columns = [desc[0] for desc in con.description]
    return [dict(zip(columns, row)) for row in rows]


def load_authors(con: duckdb.DuckDBPyConnection) -> dict[str, dict]:
    """Load all authors keyed by name_chinese."""
    rows = con.execute("""
        SELECT name_chinese, name_english, birth_year, death_year,
               wikipedia_url, pen_name_origin, pen_name_chinese, real_name_chinese
        FROM authors
    """).fetchall()
    columns = [desc[0] for desc in con.description]
    return {row[0]: dict(zip(columns, row)) for row in rows}


def build_enrichment_prompt(batch: list[dict]) -> str:
    """Build a scholarly prompt for DeepSeek to enrich a batch of works."""
    works_text = []
    for i, w in enumerate(batch, 1):
        parts = [f"{i}. work_number={w['work_number']}"]
        if w.get("title_chinese"):
            parts.append(f"title_zh={w['title_chinese']}")
        if w.get("title_english"):
            parts.append(f"title_en_current={w['title_english']}")
        if w.get("author_chinese"):
            parts.append(f"author_zh={w['author_chinese']}")
        if w.get("author_english"):
            parts.append(f"author_en_current={w['author_english']}")
        if w.get("work_link"):
            parts.append(f"link={w['work_link']}")
        works_text.append(", ".join(parts))

    works_block = "\n".join(works_text)

    # Collect unique authors in this batch for author-level enrichment
    authors_in_batch = {}
    for w in batch:
        az = w.get("author_chinese")
        if az and az not in authors_in_batch:
            authors_in_batch[az] = w.get("author_english", "")

    author_lines = []
    for az, ae in authors_in_batch.items():
        author_lines.append(f"  - {az} (current English: {ae})")
    authors_block = "\n".join(author_lines)

    return f"""As a fellow sinologist and wuxia scholar, I need your expertise to validate and enrich metadata for these Chinese literary works. Your knowledge of Chinese publishing history, author biographies, and literary conventions is essential here.

For each work below, please provide validated/corrected metadata. Be precise — use your knowledge of actual publication dates (first serialization, not later reprints), author biographical facts, and accurate literary English translations of titles.

WORKS:
{works_block}

AUTHORS IN THIS BATCH:
{authors_block}

Return a JSON object with two keys:

1. "works": an array of objects, one per work, each with:
   - "work_number": (echo back)
   - "title_english": canonical English title (proper literary translation, not pinyin. Use established translations where they exist, e.g. 射鵰英雄傳 = "Legend of the Condor Heroes")
   - "publication_year": year of first serialization (integer, or null if truly unknown)
   - "publication_note": brief publication context (e.g. "Serialized in Ming Pao, 1959–1961"), or null
   - "setting_period": historical setting if applicable (e.g. "Song Dynasty, 1199–1227"), or null for contemporary/unclear
   - "summary": 1-2 sentence synopsis without spoilers. Focus on setting, protagonist, and central conflict.
   - "category_english": genre tags as comma-separated string (from: wuxia, martial_arts, romance, historical, mystery, adventure, comedy, tragedy, revenge, political, supernatural, jianghu, science_fiction, detective, thriller, fantasy)

2. "authors": an array of objects, one per unique author, each with:
   - "name_chinese": (echo back)
   - "birth_year": integer or null
   - "death_year": integer or null (use null if still living)
   - "pen_name_origin": brief etymology of pen name if known (e.g. "From combining characters of his real name Zhā Liángyōng 查良鏞"), or null
   - "wikipedia_url": English Wikipedia URL if one exists, or null

Return ONLY the JSON object. No markdown fences, no commentary.
If you're uncertain about a field, use your best scholarly judgment rather than leaving it null."""


def call_deepseek(prompt: str) -> dict:
    """Call DeepSeek API with the enrichment prompt. Returns dict with 'works' and 'authors' keys."""
    from utils.clients.llm_config import get_llm_client
    from utils.clients.llm_client import LLMRequest

    client = get_llm_client(component="enrichment", provider="deepseek", model="deepseek-chat")

    request = LLMRequest(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=8000,
    )

    response = client.chat(request)
    content = response.text

    # Strip markdown code fences if present
    if "```json" in content:
        content = content.split("```json", 1)[1].rsplit("```", 1)[0]
    elif "```" in content:
        content = content.split("```", 1)[1].rsplit("```", 1)[0]

    try:
        result = json.loads(content.strip())
        # Handle if DeepSeek returns just a list (works only, no authors key)
        if isinstance(result, list):
            return {"works": result, "authors": []}
        if "works" not in result:
            # Might be a flat list wrapped in some other key
            return {"works": result.get("works", []), "authors": result.get("authors", [])}
        return result
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse DeepSeek response: {e}")
        logger.debug(f"Response content: {content[:500]}")
        return {"works": [], "authors": []}


def compute_work_changes(current: dict, enrichment: dict) -> dict[str, dict]:
    """Compute what would change for a single work. Returns {field: {old, new}}."""
    changes = {}

    # Fields to fill only if currently NULL or empty
    fill_if_empty = {
        "publication_year": enrichment.get("publication_year"),
        "summary": enrichment.get("summary"),
        "category_english": enrichment.get("category_english"),
        "setting_period": enrichment.get("setting_period"),
        "publication_note": enrichment.get("publication_note"),
    }

    for field, new_val in fill_if_empty.items():
        if new_val is None:
            continue
        old_val = current.get(field)
        # Treat empty string as NULL for comparison
        if not old_val and new_val:
            changes[field] = {"old": old_val, "new": new_val}

    # title_english: update only if DeepSeek disagrees AND current is generic/empty
    new_title = enrichment.get("title_english")
    if new_title:
        old_title = current.get("title_english", "")
        if old_title and old_title != new_title:
            changes["title_english_suggestion"] = {"old": old_title, "new": new_title}

    return changes


def compute_author_changes(current: dict, enrichment: dict) -> dict[str, dict]:
    """Compute what would change for a single author. Returns {field: {old, new}}."""
    changes = {}

    fill_if_empty = {
        "birth_year": enrichment.get("birth_year"),
        "death_year": enrichment.get("death_year"),
        "pen_name_origin": enrichment.get("pen_name_origin"),
        "wikipedia_url": enrichment.get("wikipedia_url"),
    }

    for field, new_val in fill_if_empty.items():
        if new_val is None:
            continue
        old_val = current.get(field)
        if not old_val and new_val:
            changes[field] = {"old": old_val, "new": new_val}

    return changes


def apply_work_changes(con: duckdb.DuckDBPyConnection, work_number: str, changes: dict[str, dict]):
    """Write work changes to DuckDB."""
    if not changes:
        return

    sets = []
    params = []
    for field, vals in changes.items():
        # Skip suggestion fields — they're for display only
        if field.endswith("_suggestion"):
            continue
        sets.append(f"{field} = ?")
        params.append(vals["new"])

    # Always set enriched_at
    sets.append("enriched_at = ?")
    params.append(datetime.now())

    if not sets:
        # Only suggestion fields, still mark as enriched
        con.execute("UPDATE works SET enriched_at = ? WHERE work_number = ?",
                     [datetime.now(), work_number])
        return

    params.append(work_number)
    sql = f"UPDATE works SET {', '.join(sets)} WHERE work_number = ?"
    con.execute(sql, params)


def apply_author_changes(con: duckdb.DuckDBPyConnection, name_chinese: str, changes: dict[str, dict]):
    """Write author changes to DuckDB."""
    if not changes:
        return

    sets = []
    params = []
    for field, vals in changes.items():
        sets.append(f"{field} = ?")
        params.append(vals["new"])

    params.append(name_chinese)
    sql = f"UPDATE authors SET {', '.join(sets)} WHERE name_chinese = ?"
    con.execute(sql, params)


def mark_enriched(con: duckdb.DuckDBPyConnection, work_number: str):
    """Mark a work as enriched even if no fields changed."""
    con.execute("UPDATE works SET enriched_at = ? WHERE work_number = ?",
                [datetime.now(), work_number])


def show_diff(label: str, changes: dict[str, dict]):
    """Display diff for a single entity."""
    if not changes:
        return
    print(f"\n  {label}:")
    for field, vals in changes.items():
        old = vals["old"] if vals["old"] is not None else "(none)"
        new = vals["new"]
        suffix = " [SUGGESTION ONLY]" if field.endswith("_suggestion") else ""
        print(f"    {field}{suffix}:")
        print(f"      - {old}")
        print(f"      + {new}")


def sync_to_status_json(con: duckdb.DuckDBPyConnection):
    """Sync enriched fields from DuckDB back to status.json files."""
    works = con.execute("""
        SELECT work_number, title_english, author_english, publication_year,
               publication_note, setting_period, summary, category_english,
               enriched_at, library_path
        FROM works
        WHERE enriched_at IS NOT NULL AND library_path IS NOT NULL
    """).fetchall()
    columns = [desc[0] for desc in con.description]

    updated = 0
    for row in works:
        w = dict(zip(columns, row))
        lib_path = LIBRARY_ROOT / w["library_path"] / "status.json"
        if not lib_path.exists():
            continue

        try:
            with open(lib_path, "r", encoding="utf-8") as f:
                status = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        changed = False
        sync_fields = {
            "title_english": w["title_english"],
            "author_english": w["author_english"],
            "publication_year": w["publication_year"],
            "publication_note": w["publication_note"],
            "setting_period": w["setting_period"],
            "description": w["summary"],  # maps summary → description in status.json
            "genre_tags": w["category_english"].split(", ") if w.get("category_english") else None,
            "enriched_at": w["enriched_at"].isoformat() if w.get("enriched_at") else None,
        }

        for field, val in sync_fields.items():
            if val is not None and status.get(field) != val:
                status[field] = val
                changed = True

        if changed:
            with open(lib_path, "w", encoding="utf-8") as f:
                json.dump(status, f, ensure_ascii=False, indent=2)
                f.write("\n")
            updated += 1

    logger.info(f"Synced {updated} status.json files")


def main():
    parser = argparse.ArgumentParser(description="Enrich library metadata via DeepSeek → DuckDB")
    parser.add_argument("--dry-run", action="store_true", help="Show proposed changes without writing")
    parser.add_argument("--diff", action="store_true", help="Show before/after diff")
    parser.add_argument("--limit", type=int, help="Process only first N works")
    parser.add_argument("--author", help="Filter by author name (English)")
    parser.add_argument("--unenriched-only", action="store_true", help="Only process works without enriched_at")
    parser.add_argument("--sync-status", action="store_true", help="Sync enriched fields back to status.json files")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help=f"Works per API call (default: {BATCH_SIZE})")
    parser.add_argument("--workers", type=int, default=50, help="Parallel API workers (default: 50)")
    parser.add_argument("--db", type=str, default=str(DB_PATH), help="Path to DuckDB database")
    args = parser.parse_args()

    # Load .env
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return 1

    con = duckdb.connect(str(db_path))

    try:
        # Schema migration
        migrate_schema(con)

        # Load works
        works = load_works(con, author_filter=args.author,
                          unenriched_only=args.unenriched_only, limit=args.limit)

        if not works:
            print("No works to process.")
            return 0

        # Load authors for change tracking
        authors_db = load_authors(con)

        # Verify work_link counts before enrichment
        wl_count = con.execute("SELECT COUNT(*) FROM works WHERE work_link IS NOT NULL").fetchone()[0]
        logger.info(f"Pre-enrichment: {wl_count} works with work_link")

        # Split into batches
        batches = []
        for batch_start in range(0, len(works), args.batch_size):
            batches.append(works[batch_start:batch_start + args.batch_size])

        total_batches = len(batches)
        print(f"\nEnriching {len(works)} works via DeepSeek "
              f"({total_batches} batches × {args.batch_size}, {args.workers} workers)...\n")

        total_work_updates = 0
        total_author_updates = 0
        total_unchanged = 0
        authors_updated = set()  # track which authors we've already updated

        if args.dry_run:
            for batch_num, batch in enumerate(batches, 1):
                print(f"\n  [DRY RUN] Batch {batch_num}/{total_batches} — {len(batch)} works:")
                for w in batch:
                    pub_yr = w.get("publication_year") or "?"
                    summary_status = "has summary" if w.get("summary") else "no summary"
                    print(f"    {w['work_number']} — {w.get('title_chinese', '?')} "
                          f"({w.get('title_english', '?')}) [{pub_yr}, {summary_status}]")
        else:
            # Parallel API calls, serial DB writes
            def fetch_batch(batch_num_and_batch):
                batch_num, batch = batch_num_and_batch
                prompt = build_enrichment_prompt(batch)
                try:
                    result = call_deepseek(prompt)
                    logger.info(f"Batch {batch_num}/{total_batches} returned "
                                f"{len(result.get('works', []))} works")
                    return batch_num, batch, result
                except Exception as e:
                    logger.error(f"Batch {batch_num}/{total_batches} failed: {e}")
                    return batch_num, batch, None

            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = {pool.submit(fetch_batch, (i, b)): i
                           for i, b in enumerate(batches, 1)}

                for future in as_completed(futures):
                    batch_num, batch, result = future.result()

                    if result is None:
                        # API failed — mark all as enriched so we don't endlessly retry
                        for work in batch:
                            mark_enriched(con, work["work_number"])
                            total_unchanged += 1
                        continue

                    enriched_works = result.get("works", [])
                    enriched_authors = result.get("authors", [])

                    work_enrichment_map = {e.get("work_number"): e for e in enriched_works}

                    # Apply work-level changes
                    for work in batch:
                        wn = work["work_number"]
                        enrichment = work_enrichment_map.get(wn)

                        if not enrichment:
                            logger.warning(f"  No enrichment returned for {wn}")
                            mark_enriched(con, wn)
                            total_unchanged += 1
                            continue

                        changes = compute_work_changes(work, enrichment)

                        if changes:
                            total_work_updates += 1
                            if args.diff:
                                show_diff(f"{wn} ({work.get('title_chinese', '')})", changes)
                            apply_work_changes(con, wn, changes)
                        else:
                            total_unchanged += 1
                            mark_enriched(con, wn)

                    # Apply author-level changes (once per unique author per run)
                    for author_enrichment in enriched_authors:
                        name_zh = author_enrichment.get("name_chinese")
                        if not name_zh or name_zh in authors_updated:
                            continue
                        if name_zh not in authors_db:
                            logger.warning(f"  Author '{name_zh}' not in authors table, skipping")
                            continue

                        current_author = authors_db[name_zh]
                        changes = compute_author_changes(current_author, author_enrichment)

                        if changes:
                            total_author_updates += 1
                            authors_updated.add(name_zh)
                            if args.diff:
                                show_diff(f"AUTHOR: {name_zh} ({current_author.get('name_english', '')})", changes)
                            apply_author_changes(con, name_zh, changes)
                            for field, vals in changes.items():
                                authors_db[name_zh][field] = vals["new"]

        # Verify work_link preserved
        wl_count_after = con.execute("SELECT COUNT(*) FROM works WHERE work_link IS NOT NULL").fetchone()[0]
        if wl_count_after != wl_count:
            logger.error(f"work_link count changed! Before: {wl_count}, After: {wl_count_after}")
        else:
            logger.info(f"Post-enrichment: {wl_count_after} works with work_link (preserved)")

        # Sync to status.json if requested
        if args.sync_status and not args.dry_run:
            sync_to_status_json(con)

        # Summary
        print(f"\n{'=' * 60}")
        print(f"  Enrichment complete")
        print(f"  Works updated:    {total_work_updates}")
        print(f"  Works unchanged:  {total_unchanged}")
        print(f"  Authors updated:  {total_author_updates}")
        print(f"  Total processed:  {len(works)}")
        print(f"{'=' * 60}")

    finally:
        con.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
