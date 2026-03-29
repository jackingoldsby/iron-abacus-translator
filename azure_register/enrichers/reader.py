#!/usr/bin/env python3
"""
ReaderEnricher — reader-oriented metadata via DeepSeek.

Fields: rating_tier, rating_note, writing_style, themes, mood,
        comparable_works, wuxia_era
Author fields: writing_style, best_known_for
"""

import logging
from typing import Optional

from azure_register.config.defaults import (
    MAX_TOKENS,
    READER_BATCH_SIZE,
    READER_TEMPERATURE,
)
from azure_register.enrichers.base import BaseEnricher
from azure_register.prompts.reader import format_batch, validate_rating_tier
from azure_register.utils.llm_client import LLMRequest, get_deepseek_client

logger = logging.getLogger(__name__)

WORK_COLUMNS = [
    "work_id", "work_number", "title_chinese", "title_english",
    "author_chinese", "author_english", "publication_year",
    "summary", "category_english", "setting_period", "publication_note",
    "rating_tier", "rating_note", "writing_style", "themes", "mood",
    "comparable_works", "wuxia_era", "reader_enriched_at",
    "a.name_english AS author_name_english",
    "a.writing_style AS author_writing_style",
    "a.best_known_for AS author_best_known_for",
]

AUTHOR_COLUMNS = [
    "name_chinese", "name_english", "birth_year", "death_year",
    "description", "writing_style", "best_known_for",
]

WORK_FILL_FIELDS = [
    "rating_tier", "rating_note", "writing_style", "themes",
    "mood", "comparable_works", "wuxia_era",
]

AUTHOR_FILL_FIELDS = ["writing_style", "best_known_for"]


class ReaderEnricher(BaseEnricher):
    """Enrich works with reader-oriented metadata via DeepSeek."""

    def __init__(self, **kwargs):
        kwargs.setdefault("batch_size", READER_BATCH_SIZE)
        super().__init__(**kwargs)

    def enrich(
        self,
        author_filter: Optional[str] = None,
        unenriched_only: bool = False,
        limit: Optional[int] = None,
    ):
        """Run reader enrichment."""
        con = self.connect()
        try:
            self.migrate_schema(con)

            works = self.fetch_works(
                con, WORK_COLUMNS,
                author_filter=author_filter,
                unenriched_only=unenriched_only,
                unenriched_column="reader_enriched_at",
                limit=limit,
            )

            if not works:
                print("No works to process.")
                return

            authors_db = self.fetch_authors(con, AUTHOR_COLUMNS)
            batches = self.make_batches(works)
            total_batches = len(batches)

            print(
                f"\nReader-enriching {len(works)} works via DeepSeek "
                f"({total_batches} batches x {self.batch_size}, {self.workers} workers)...\n"
            )

            if self.dry_run:
                self._show_dry_run(batches, total_batches)
            else:
                self._run_enrichment(con, batches, total_batches, authors_db)
                self._show_tier_distribution(con)

            self.print_summary("Reader enrichment", len(works))
        finally:
            con.close()

    def _show_dry_run(self, batches, total_batches):
        for batch_num, batch in enumerate(batches, 1):
            print(f"\n  [DRY RUN] Batch {batch_num}/{total_batches} -- {len(batch)} works:")
            for w in batch:
                tier = w.get("rating_tier") or "?"
                style = "has style" if w.get("writing_style") else "no style"
                print(
                    f"    {w['work_number']} -- {w.get('title_chinese', '?')} "
                    f"({w.get('title_english', '?')}) [{tier}, {style}]"
                )

    def _run_enrichment(self, con, batches, total_batches, authors_db):
        client = get_deepseek_client()
        authors_updated: set[str] = set()

        def fetch_batch(batch_num_and_batch):
            batch_num, batch = batch_num_and_batch
            prompt = format_batch(batch, authors_db)
            try:
                request = LLMRequest(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=READER_TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                )
                response = client.chat(request)
                result = response.parsed
                if result is None:
                    logger.error(f"Batch {batch_num}/{total_batches} returned unparseable JSON")
                    return batch_num, batch, None
                if isinstance(result, list):
                    result = {"works": result, "authors": []}
                if "works" not in result:
                    result = {"works": result.get("works", []), "authors": result.get("authors", [])}
                logger.info(
                    f"Batch {batch_num}/{total_batches} returned "
                    f"{len(result.get('works', []))} works"
                )
                return batch_num, batch, result
            except Exception as e:
                logger.error(f"Batch {batch_num}/{total_batches} failed: {e}")
                return batch_num, batch, None

        for batch_num, batch, result in self.run_parallel(batches, fetch_batch):
            if result is None:
                for work in batch:
                    self.mark_enriched(con, work["work_number"], "reader_enriched_at")
                    self.total_unchanged += 1
                continue

            work_map = {e.get("work_number"): e for e in result.get("works", [])}

            for work in batch:
                wn = work["work_number"]
                enrichment = work_map.get(wn)

                if not enrichment:
                    logger.warning(f"  No enrichment returned for {wn}")
                    self.mark_enriched(con, wn, "reader_enriched_at")
                    self.total_unchanged += 1
                    continue

                # Validate rating_tier before computing changes
                enrichment["rating_tier"] = validate_rating_tier(enrichment.get("rating_tier"))

                changes = self.compute_changes(work, enrichment, WORK_FILL_FIELDS)

                if changes:
                    self.total_work_updates += 1
                    if self.diff:
                        self.show_diff(f"{wn} ({work.get('title_chinese', '')})", changes)
                    self.apply_work_changes(con, wn, changes, "reader_enriched_at")
                else:
                    self.total_unchanged += 1
                    self.mark_enriched(con, wn, "reader_enriched_at")

            for author_enrichment in result.get("authors", []):
                name_zh = author_enrichment.get("name_chinese")
                if not name_zh or name_zh in authors_updated:
                    continue
                if name_zh not in authors_db:
                    logger.warning(f"  Author '{name_zh}' not in authors table, skipping")
                    continue

                current_author = authors_db[name_zh]
                changes = self.compute_changes(current_author, author_enrichment, AUTHOR_FILL_FIELDS)

                if changes:
                    self.total_author_updates += 1
                    authors_updated.add(name_zh)
                    if self.diff:
                        self.show_diff(
                            f"AUTHOR: {name_zh} ({current_author.get('name_english', '')})",
                            changes,
                        )
                    self.apply_author_changes(con, name_zh, changes)
                    for field, vals in changes.items():
                        authors_db[name_zh][field] = vals["new"]

    def _show_tier_distribution(self, con):
        if self.total_work_updates > 0:
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
