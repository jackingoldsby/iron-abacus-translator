#!/usr/bin/env python3
"""
DEPRECATED: Use azure_register instead:
    cd azure_register && python -m cli.enrich reader --dry-run

Reader-Oriented Metadata Enrichment via DeepSeek → DuckDB

Enriches works and authors with subjective/evaluative metadata that helps
readers decide what to read next. Separate from factual enrichment — different
prompt, different fields.

Enriched fields:
    works: rating_tier, rating_note, writing_style, themes, mood,
           comparable_works, wuxia_era, reader_enriched_at
    authors: writing_style, best_known_for

Usage:
    python dev/admin/enrich_reader_metadata.py --limit 5 --dry-run
    python dev/admin/enrich_reader_metadata.py --limit 5 --diff
    python dev/admin/enrich_reader_metadata.py --author "Jin Yong" --diff
    python dev/admin/enrich_reader_metadata.py --unenriched-only --diff
    python dev/admin/enrich_reader_metadata.py
"""

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import duckdb

# Resolve project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent / "iron_abacus_translator"
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = Path.home() / "project_files" / "translation_project" / "db" / "works_translator.duckdb"

BATCH_SIZE = 10  # More tokens needed per work than factual enrichment

VALID_RATING_TIERS = {"masterpiece", "acclaimed", "solid", "minor", "obscure", "controversial"}


def migrate_schema(con: duckdb.DuckDBPyConnection):
    """Add reader-enrichment columns to works and authors tables."""
    migrations = [
        # Works table — reader enrichment
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS rating_tier VARCHAR",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS rating_note VARCHAR",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS writing_style VARCHAR",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS themes VARCHAR",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS mood VARCHAR",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS comparable_works VARCHAR",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS wuxia_era VARCHAR",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS reader_enriched_at TIMESTAMP",
        # Authors table — reader enrichment
        "ALTER TABLE authors ADD COLUMN IF NOT EXISTS writing_style VARCHAR",
        "ALTER TABLE authors ADD COLUMN IF NOT EXISTS best_known_for VARCHAR",
    ]
    for sql in migrations:
        try:
            con.execute(sql)
        except duckdb.CatalogException:
            pass
    logger.info("Reader enrichment schema migration complete")


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
            w.publication_year,
            w.summary,
            w.category_english,
            w.setting_period,
            w.publication_note,
            w.rating_tier,
            w.rating_note,
            w.writing_style,
            w.themes,
            w.mood,
            w.comparable_works,
            w.wuxia_era,
            w.reader_enriched_at,
            a.name_english AS author_name_english,
            a.writing_style AS author_writing_style,
            a.best_known_for AS author_best_known_for
        FROM works w
        LEFT JOIN authors a ON w.author_chinese = a.name_chinese
        WHERE 1=1
    """
    params = []

    if author_filter:
        query += " AND LOWER(w.author_english) LIKE ?"
        params.append(f"%{author_filter.lower()}%")

    if unenriched_only:
        query += " AND w.reader_enriched_at IS NULL"

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
               description, writing_style, best_known_for
        FROM authors
    """).fetchall()
    columns = [desc[0] for desc in con.description]
    return {row[0]: dict(zip(columns, row)) for row in rows}


def build_enrichment_prompt(batch: list[dict]) -> str:
    """Build a scholarly prompt for DeepSeek to provide reader-oriented assessments."""
    works_text = []
    for i, w in enumerate(batch, 1):
        parts = [f"{i}. work_number={w['work_number']}"]
        if w.get("title_chinese"):
            parts.append(f"title_zh={w['title_chinese']}")
        if w.get("title_english"):
            parts.append(f"title_en={w['title_english']}")
        if w.get("author_chinese"):
            parts.append(f"author_zh={w['author_chinese']}")
        if w.get("author_english"):
            parts.append(f"author_en={w['author_english']}")
        if w.get("publication_year"):
            parts.append(f"pub_year={w['publication_year']}")
        if w.get("summary"):
            parts.append(f"summary={w['summary']}")
        if w.get("category_english"):
            parts.append(f"genre={w['category_english']}")
        if w.get("setting_period"):
            parts.append(f"setting={w['setting_period']}")
        works_text.append(", ".join(parts))

    works_block = "\n".join(works_text)

    # Collect unique authors in this batch
    authors_in_batch = {}
    for w in batch:
        az = w.get("author_chinese")
        if az and az not in authors_in_batch:
            authors_in_batch[az] = {
                "name_english": w.get("author_english", ""),
                "name_chinese": az,
            }

    author_lines = []
    for az, info in authors_in_batch.items():
        author_lines.append(f"  - {az} ({info['name_english']})")
    authors_block = "\n".join(author_lines)

    return f"""As a fellow wuxia literary critic and Chinese fiction scholar, I need your expertise to provide reader-oriented assessments of these works. Your deep knowledge of the wuxia canon, author reputations, and genre evolution is essential.

For each work, provide subjective but informed literary assessments that help a reader decide what to read next. Rate works relative to the wuxia/martial arts fiction genre, not all literature.

WORKS:
{works_block}

AUTHORS IN THIS BATCH:
{authors_block}

Return a JSON object with two keys:

1. "works": an array of objects, one per work, each with:
   - "work_number": (echo back)
   - "rating_tier": EXACTLY one of: "masterpiece", "acclaimed", "solid", "minor", "obscure", "controversial"
     * masterpiece: universally recognized pinnacle of the genre (reserve for ~5-10 works total across all wuxia)
     * acclaimed: widely praised, considered among an author's best or a genre landmark
     * solid: well-crafted, enjoyable, but not the author's peak work
     * minor: lesser work, perhaps early/experimental or formulaic
     * obscure: little-known, limited critical attention
     * controversial: divisive — some love it, some hate it, or significant critical debate
   - "rating_note": 1-2 sentences of critical context. WHY this tier? What do critics/readers say? (e.g. "Widely considered Liang Yusheng's finest work. Defined the 'new school' wuxia genre alongside Jin Yong's early novels.")
   - "writing_style": comma-separated style descriptors from this vocabulary (use 2-5):
     poetic, lyrical, spare, dense, cinematic, theatrical, cerebral, visceral,
     character-driven, plot-driven, slow-burn, fast-paced, episodic, tightly-plotted,
     literary, pulpy, philosophical, humorous, satirical, tragic, romantic,
     classical-prose, vernacular, experimental
   - "themes": comma-separated thematic tags (use 2-5):
     forbidden love, revenge cycle, political intrigue, identity, loyalty vs righteousness,
     jianghu honor code, master-disciple bond, power corruption, redemption, sacrifice,
     family legacy, ethnic conflict, dynastic collapse, wandering hero, reclusion,
     coming-of-age, gender subversion, class struggle, fate vs free will, brotherhood
     (or other relevant themes — not limited to this list)
   - "mood": comma-separated tone/atmosphere tags (use 2-4):
     dark, melancholy, romantic, suspenseful, epic, intimate, nostalgic, brooding,
     whimsical, bleak, triumphant, bittersweet, tense, lighthearted, ominous,
     grand, meditative, frenetic
   - "comparable_works": 1 sentence — "If you liked X, you'll enjoy this" or "Fans of X will appreciate Y". Reference well-known wuxia works, or other works in this batch where relevant.
   - "wuxia_era": place in genre evolution — era label + brief context. Format: "era_label (context)"
     * "foundational (1950s new-school pioneer)"
     * "golden age (1960s-70s peak of Jin Yong/Gu Long rivalry)"
     * "late classical (1980s mature genre)"
     * "post-classical (1990s+ genre reinvention)"
     * "pre-modern (Republican era or earlier)"

2. "authors": an array of objects, one per unique author, each with:
   - "name_chinese": (echo back)
   - "writing_style": author's signature literary style in 1-2 sentences (e.g. "Poetic classical prose with deep historical research. Known for strong female protagonists and morally complex villains.")
   - "best_known_for": signature works and contributions in 1-2 sentences (e.g. "Pioneer of 'new school' wuxia alongside Jin Yong. Best known for Seven Swords of Mount Heaven and The White-Haired Demoness.")

Return ONLY the JSON object. No markdown fences, no commentary.
If you're uncertain about a specific work, use your best scholarly judgment — an informed assessment is better than null."""


def call_deepseek(prompt: str) -> dict:
    """Call DeepSeek API with the enrichment prompt."""
    from utils.clients.llm_config import get_llm_client
    from utils.clients.llm_client import LLMRequest

    client = get_llm_client(component="enrichment", provider="deepseek", model="deepseek-chat")

    request = LLMRequest(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
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
        if isinstance(result, list):
            return {"works": result, "authors": []}
        if "works" not in result:
            return {"works": result.get("works", []), "authors": result.get("authors", [])}
        return result
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse DeepSeek response: {e}")
        logger.debug(f"Response content: {content[:500]}")
        return {"works": [], "authors": []}


def validate_rating_tier(tier: str | None) -> str | None:
    """Validate and normalize rating_tier to one of the 6 fixed values."""
    if not tier:
        return None
    normalized = tier.strip().lower()
    if normalized in VALID_RATING_TIERS:
        return normalized
    # Try fuzzy matching for common variations
    for valid in VALID_RATING_TIERS:
        if valid in normalized or normalized in valid:
            return valid
    logger.warning(f"Invalid rating_tier '{tier}', discarding")
    return None


def compute_work_changes(current: dict, enrichment: dict) -> dict[str, dict]:
    """Compute what would change for a single work. Returns {field: {old, new}}."""
    changes = {}

    # Validate rating_tier
    rating_tier = validate_rating_tier(enrichment.get("rating_tier"))

    fill_if_empty = {
        "rating_tier": rating_tier,
        "rating_note": enrichment.get("rating_note"),
        "writing_style": enrichment.get("writing_style"),
        "themes": enrichment.get("themes"),
        "mood": enrichment.get("mood"),
        "comparable_works": enrichment.get("comparable_works"),
        "wuxia_era": enrichment.get("wuxia_era"),
    }

    for field, new_val in fill_if_empty.items():
        if new_val is None:
            continue
        old_val = current.get(field)
        if not old_val and new_val:
            changes[field] = {"old": old_val, "new": new_val}

    return changes


def compute_author_changes(current: dict, enrichment: dict) -> dict[str, dict]:
    """Compute what would change for a single author. Returns {field: {old, new}}."""
    changes = {}

    fill_if_empty = {
        "writing_style": enrichment.get("writing_style"),
        "best_known_for": enrichment.get("best_known_for"),
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
        sets.append(f"{field} = ?")
        params.append(vals["new"])

    # Always set reader_enriched_at
    sets.append("reader_enriched_at = ?")
    params.append(datetime.now())

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
    """Mark a work as reader-enriched even if no fields changed."""
    con.execute("UPDATE works SET reader_enriched_at = ? WHERE work_number = ?",
                [datetime.now(), work_number])


def show_diff(label: str, changes: dict[str, dict]):
    """Display diff for a single entity."""
    if not changes:
        return
    print(f"\n  {label}:")
    for field, vals in changes.items():
        old = vals["old"] if vals["old"] is not None else "(none)"
        new = vals["new"]
        print(f"    {field}:")
        print(f"      - {old}")
        print(f"      + {new}")


def main():
    parser = argparse.ArgumentParser(description="Enrich reader-oriented metadata via DeepSeek → DuckDB")
    parser.add_argument("--dry-run", action="store_true", help="Show proposed changes without writing")
    parser.add_argument("--diff", action="store_true", help="Show before/after diff")
    parser.add_argument("--limit", type=int, help="Process only first N works")
    parser.add_argument("--author", help="Filter by author name (English)")
    parser.add_argument("--unenriched-only", action="store_true", help="Only process works without reader_enriched_at")
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
        migrate_schema(con)

        works = load_works(con, author_filter=args.author,
                          unenriched_only=args.unenriched_only, limit=args.limit)

        if not works:
            print("No works to process.")
            return 0

        authors_db = load_authors(con)

        # Split into batches
        batches = []
        for batch_start in range(0, len(works), args.batch_size):
            batches.append(works[batch_start:batch_start + args.batch_size])

        total_batches = len(batches)
        print(f"\nReader-enriching {len(works)} works via DeepSeek "
              f"({total_batches} batches × {args.batch_size}, {args.workers} workers)...\n")

        total_work_updates = 0
        total_author_updates = 0
        total_unchanged = 0
        authors_updated = set()

        if args.dry_run:
            for batch_num, batch in enumerate(batches, 1):
                print(f"\n  [DRY RUN] Batch {batch_num}/{total_batches} — {len(batch)} works:")
                for w in batch:
                    tier = w.get("rating_tier") or "?"
                    style = "has style" if w.get("writing_style") else "no style"
                    print(f"    {w['work_number']} — {w.get('title_chinese', '?')} "
                          f"({w.get('title_english', '?')}) [{tier}, {style}]")
        else:
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
                        for work in batch:
                            mark_enriched(con, work["work_number"])
                            total_unchanged += 1
                        continue

                    enriched_works = result.get("works", [])
                    enriched_authors = result.get("authors", [])

                    work_enrichment_map = {e.get("work_number"): e for e in enriched_works}

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

        # Summary
        print(f"\n{'=' * 60}")
        print(f"  Reader enrichment complete")
        print(f"  Works updated:    {total_work_updates}")
        print(f"  Works unchanged:  {total_unchanged}")
        print(f"  Authors updated:  {total_author_updates}")
        print(f"  Total processed:  {len(works)}")
        print(f"{'=' * 60}")

        # Show rating_tier distribution if any updates
        if total_work_updates > 0 and not args.dry_run:
            print("\n  Rating tier distribution:")
            rows = con.execute("""
                SELECT rating_tier, COUNT(*) as cnt
                FROM works
                WHERE rating_tier IS NOT NULL
                GROUP BY rating_tier
                ORDER BY cnt DESC
            """).fetchall()
            for tier, cnt in rows:
                print(f"    {tier}: {cnt}")

    finally:
        con.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
