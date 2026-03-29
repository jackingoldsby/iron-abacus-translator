#!/usr/bin/env python3
"""
LibraryEnricher — factual metadata via DeepSeek.

Fields: publication_year, publication_note, setting_period, summary, category_english
Author fields: birth_year, death_year, pen_name_origin, wikipedia_url
"""

import logging
from typing import Optional

from azure_register.config.defaults import (
    LIBRARY_BATCH_SIZE,
    LIBRARY_TEMPERATURE,
    MAX_TOKENS,
)
from azure_register.enrichers.base import BaseEnricher
from azure_register.prompts.library import format_batch
from azure_register.utils.llm_client import LLMRequest, get_deepseek_client

logger = logging.getLogger(__name__)

# Columns queried from works
WORK_COLUMNS = [
    "work_id", "work_number", "title_chinese", "title_english",
    "author_chinese", "author_english", "work_link",
    "publication_year", "summary", "category_english",
    "setting_period", "publication_note", "enriched_at", "library_path",
    "a.name_english AS author_name_english",
    "a.birth_year AS author_birth_year",
    "a.death_year AS author_death_year",
    "a.wikipedia_url AS author_wikipedia_url",
    "a.pen_name_origin AS author_pen_name_origin",
]

AUTHOR_COLUMNS = [
    "name_chinese", "name_english", "birth_year", "death_year",
    "wikipedia_url", "pen_name_origin", "pen_name_chinese", "real_name_chinese",
]

# Fields to fill if empty
WORK_FILL_FIELDS = [
    "publication_year", "summary", "category_english",
    "setting_period", "publication_note",
]

AUTHOR_FILL_FIELDS = [
    "birth_year", "death_year", "pen_name_origin", "wikipedia_url",
]


class LibraryEnricher(BaseEnricher):
    """Enrich works with factual metadata via DeepSeek."""

    def __init__(self, **kwargs):
        kwargs.setdefault("batch_size", LIBRARY_BATCH_SIZE)
        super().__init__(**kwargs)

    def enrich(
        self,
        author_filter: Optional[str] = None,
        unenriched_only: bool = False,
        limit: Optional[int] = None,
        sync_status: bool = False,
    ):
        """Run library enrichment."""
        con = self.connect()
        try:
            self.migrate_schema(con)

            works = self.fetch_works(
                con, WORK_COLUMNS,
                author_filter=author_filter,
                unenriched_only=unenriched_only,
                unenriched_column="enriched_at",
                limit=limit,
            )

            if not works:
                print("No works to process.")
                return

            authors_db = self.fetch_authors(con, AUTHOR_COLUMNS)
            batches = self.make_batches(works)
            total_batches = len(batches)

            print(
                f"\nEnriching {len(works)} works via DeepSeek "
                f"({total_batches} batches x {self.batch_size}, {self.workers} workers)...\n"
            )

            if self.dry_run:
                self._show_dry_run(batches, total_batches)
            else:
                self._run_enrichment(con, batches, total_batches, authors_db)

                if sync_status:
                    from azure_register.enrichers._status_sync import sync_to_status_json
                    sync_to_status_json(con)

            self.print_summary("Library enrichment", len(works))
        finally:
            con.close()

    def _show_dry_run(self, batches: list[list], total_batches: int):
        for batch_num, batch in enumerate(batches, 1):
            print(f"\n  [DRY RUN] Batch {batch_num}/{total_batches} -- {len(batch)} works:")
            for w in batch:
                pub_yr = w.get("publication_year") or "?"
                summary_status = "has summary" if w.get("summary") else "no summary"
                print(
                    f"    {w['work_number']} -- {w.get('title_chinese', '?')} "
                    f"({w.get('title_english', '?')}) [{pub_yr}, {summary_status}]"
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
                    temperature=LIBRARY_TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                )
                response = client.chat(request)
                result = response.parsed
                if result is None:
                    logger.error(f"Batch {batch_num}/{total_batches} returned unparseable JSON")
                    return batch_num, batch, None
                # Normalize
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
                    self.mark_enriched(con, work["work_number"], "enriched_at")
                    self.total_unchanged += 1
                continue

            work_map = {e.get("work_number"): e for e in result.get("works", [])}

            for work in batch:
                wn = work["work_number"]
                enrichment = work_map.get(wn)

                if not enrichment:
                    logger.warning(f"  No enrichment returned for {wn}")
                    self.mark_enriched(con, wn, "enriched_at")
                    self.total_unchanged += 1
                    continue

                changes = self.compute_changes(work, enrichment, WORK_FILL_FIELDS)

                # title_english suggestion (don't auto-overwrite)
                new_title = enrichment.get("title_english")
                if new_title:
                    old_title = work.get("title_english", "")
                    if old_title and old_title != new_title:
                        changes["title_english_suggestion"] = {"old": old_title, "new": new_title}

                if changes:
                    self.total_work_updates += 1
                    if self.diff:
                        self.show_diff(f"{wn} ({work.get('title_chinese', '')})", changes)
                    self.apply_work_changes(con, wn, changes, "enriched_at")
                else:
                    self.total_unchanged += 1
                    self.mark_enriched(con, wn, "enriched_at")

            # Author-level changes
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
