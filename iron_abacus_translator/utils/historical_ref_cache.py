#!/usr/bin/env python3
"""
Historical Reference Cache

Incrementally-built cache of Wikipedia summaries for historical terms
encountered during translation. Each term is fetched once from Wikipedia
and stored in DuckDB for reuse across all future books.

Usage:
    from utils.historical_ref_cache import HistoricalRefCache

    cache = HistoricalRefCache()

    # Look up or fetch a term
    entry = cache.get_or_fetch("御史台", wiki_title="Censorate")
    # → {"term_zh": "御史台", "term_en": "Censorate", "summary": "The Censorate was...", ...}

    # Just check the cache (no fetch)
    entry = cache.get("御史台")

    # Enrich a footnote with cached context
    cache.enrich_footnote({"ideogram": "御史台", "explanation": "..."})
"""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

MEDIAWIKI_API = "https://en.wikipedia.org/w/api.php"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS historical_references (
    term_zh         VARCHAR NOT NULL PRIMARY KEY,
    term_py         VARCHAR,
    term_en         VARCHAR,
    category        VARCHAR,
    summary         VARCHAR,
    wiki_url        VARCHAR,
    wiki_title      VARCHAR,
    dynasty_context VARCHAR,
    added_by_work   VARCHAR,
    added_at        TIMESTAMP,
    fetch_failed    BOOLEAN DEFAULT FALSE
);
"""

# Categories for historical references
CATEGORIES = {
    "institution": "Government office, department, or civil service body",
    "title": "Official title, rank, or honorific",
    "place": "Historical place name, city, or region",
    "event": "Historical event, battle, or incident",
    "concept": "Cultural, philosophical, or religious concept",
    "text": "Classical text, literary work, or scripture",
    "practice": "Custom, ritual, or martial tradition",
    "other": "Uncategorized historical reference",
}


def _extract_wiki_search_term(explanation: str, pinyin: str = "") -> Optional[str]:
    """Extract a plausible English Wikipedia search term from a footnote explanation.

    Looks for patterns like:
    - "The Kangxi Emperor (r. 1661-1722)..." → "Kangxi Emperor"
    - "Kuíxīng, the 'Legs' constellation..." → "Kuixing constellation"
    - "Wudang Mountains, a sacred Daoist..." → "Wudang Mountains"
    - "A traditional Chinese unit..." → None (too generic, skip)

    Returns None if no good search term can be extracted.
    """
    import re

    # Strip markdown formatting
    explanation = explanation.replace("*", "").replace("_", " ").strip()

    # Skip clearly fictional/generic explanations
    generic_starts = (
        "a fictional", "a coarse", "a cryptic",
        "an idiom meaning", "a proverb meaning",
        "literally ", "a respectful term", "a common",
    )
    lower = explanation.lower().strip()
    if any(lower.startswith(g) for g in generic_starts):
        return None

    # Skip if explanation is too short to contain a searchable term
    if len(explanation) < 20:
        return None

    # Strip pinyin tone marks for Wikipedia search
    def _strip_tones(s):
        return re.sub(r'[āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]', lambda c: {
            'ā':'a','á':'a','ǎ':'a','à':'a','ē':'e','é':'e','ě':'e','è':'e',
            'ī':'i','í':'i','ǐ':'i','ì':'i','ō':'o','ó':'o','ǒ':'o','ò':'o',
            'ū':'u','ú':'u','ǔ':'u','ù':'u','ǖ':'u','ǘ':'u','ǚ':'u','ǜ':'u',
        }.get(c.group(), c.group()), s)

    # Pattern 1: "Name (dates/context)" or "Name, description"
    m = re.match(r'^([A-Z\u00C0-\u024F][^(,]{2,40}?)(?:\s*\(|\s*,)', explanation)
    if m:
        term = _strip_tones(m.group(1).strip())
        if len(term) >= 3:
            return term

    # Pattern 2: "The 'Name' ..." or "The Name of ..."
    m = re.match(r'^The\s+["\u201c\']?([A-Z\u00C0-\u024F][^"\u201d\']{2,40}?)["\u201d\']?\s', explanation)
    if m:
        term = _strip_tones(m.group(1).strip())
        if len(term) >= 3:
            return term

    # Pattern 3: "A/The X, a Y that..." — extract X
    m = re.match(r'^(?:The|A)\s+([A-Z\u00C0-\u024F][^,]{2,40}),\s+(?:a |the |one of )', explanation)
    if m:
        term = _strip_tones(m.group(1).strip())
        if len(term) >= 4:
            return term

    # Pattern 4: "'Name' in single quotes
    m = re.search(r"['\u2018]([A-Z][^'\u2019]{2,30})['\u2019]", explanation)
    if m:
        term = _strip_tones(m.group(1).strip())
        if len(term) >= 4:
            return term

    return None


def _fetch_wikipedia_intro(title: str, max_chars: int = 600) -> Optional[str]:
    """Fetch the intro extract of a Wikipedia article via MediaWiki API.

    Tries exact title first, then falls back to search API.
    """
    headers = {
        "User-Agent": "IronAbacusTranslator/1.0 (https://github.com/iron-abacus; bot-traffic@wikimedia.org)",
    }

    # Try exact title match first
    result = _wiki_query_extract(title, headers, max_chars)
    if result:
        return result

    # Fallback: search API to find the right article
    try:
        search_params = {
            "action": "query",
            "list": "search",
            "srsearch": title,
            "srlimit": 1,
            "format": "json",
        }
        resp = httpx.get(MEDIAWIKI_API, params=search_params, headers=headers, timeout=15)
        resp.raise_for_status()
        results = resp.json().get("query", {}).get("search", [])
        if results:
            found_title = results[0].get("title", "")
            if found_title:
                return _wiki_query_extract(found_title, headers, max_chars)
    except Exception as e:
        logger.debug(f"Wikipedia search failed for '{title}': {e}")

    return None


def _wiki_query_extract(title: str, headers: dict, max_chars: int = 600) -> Optional[str]:
    """Query Wikipedia for a specific article's intro extract."""
    params = {
        "action": "query",
        "titles": title.replace("_", " "),
        "prop": "extracts",
        "exintro": "true",
        "explaintext": "true",
        "format": "json",
    }

    try:
        resp = httpx.get(MEDIAWIKI_API, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            if page_id == "-1":
                return None
            extract = page.get("extract", "")
            if extract:
                if len(extract) > max_chars:
                    cut = extract[:max_chars]
                    last_period = cut.rfind(". ")
                    if last_period > max_chars // 3:
                        extract = cut[:last_period + 1]
                    else:
                        extract = cut + "..."
                return extract.strip()
    except Exception as e:
        logger.debug(f"Wikipedia query failed for '{title}': {e}")

    return None


def _wiki_url_from_title(title: str) -> str:
    """Build a Wikipedia URL from an article title."""
    return f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"


class HistoricalRefCache:
    """Incrementally-built cache of Wikipedia summaries for historical terms.

    Terms are fetched on demand and stored in DuckDB. Once cached, they're
    available instantly for all future translation jobs.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path
        self._mem_cache: Optional[Dict[str, dict]] = None

    def _get_connection(self):
        if self._db_path:
            import duckdb
            return duckdb.connect(str(self._db_path))
        from utils.db import connect_catalog
        return connect_catalog()

    def _ensure_table(self, conn):
        """Create the table if it doesn't exist."""
        conn.execute(CREATE_TABLE_SQL)

    def _load_cache(self):
        """Load all cached entries into memory."""
        if self._mem_cache is not None:
            return

        self._mem_cache = {}
        try:
            conn = self._get_connection()
            self._ensure_table(conn)

            rows = conn.execute(
                "SELECT term_zh, term_py, term_en, category, summary, "
                "wiki_url, wiki_title, dynasty_context, added_by_work, fetch_failed "
                "FROM historical_references"
            ).fetchall()

            columns = [
                'term_zh', 'term_py', 'term_en', 'category', 'summary',
                'wiki_url', 'wiki_title', 'dynasty_context', 'added_by_work',
                'fetch_failed',
            ]

            for row in rows:
                d = dict(zip(columns, row))
                self._mem_cache[d['term_zh']] = d

            conn.close()
            logger.debug(f"Loaded {len(self._mem_cache)} historical references from cache")

        except Exception as e:
            logger.error(f"Failed to load historical reference cache: {e}")
            self._mem_cache = {}

    def get(self, term_zh: str) -> Optional[dict]:
        """Look up a term in the cache. Returns None if not cached."""
        self._load_cache()
        return self._mem_cache.get(term_zh)

    def get_or_fetch(
        self,
        term_zh: str,
        wiki_title: Optional[str] = None,
        term_en: Optional[str] = None,
        term_py: Optional[str] = None,
        category: Optional[str] = None,
        dynasty_context: Optional[str] = None,
        work_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Look up a term; if not cached, fetch from Wikipedia and store.

        Args:
            term_zh: Chinese term (e.g. "御史台")
            wiki_title: Wikipedia article title for lookup (e.g. "Censorate")
            term_en: English name (if known)
            term_py: Pinyin (if known)
            category: One of CATEGORIES keys
            dynasty_context: Which dynasty this is relevant to
            work_id: Which work triggered the lookup (for provenance)

        Returns:
            Cached dict with summary, or None if fetch failed and no prior cache.
        """
        self._load_cache()

        # Return cached if available and not a failed fetch
        existing = self._mem_cache.get(term_zh)
        if existing and not existing.get('fetch_failed'):
            return existing

        # Need to fetch — must have a wiki_title
        if not wiki_title:
            logger.debug(f"No wiki_title for '{term_zh}' — cannot fetch")
            return existing  # Return failed entry or None

        summary = _fetch_wikipedia_intro(wiki_title)
        wiki_url = _wiki_url_from_title(wiki_title)

        entry = {
            'term_zh': term_zh,
            'term_py': term_py or '',
            'term_en': term_en or wiki_title.replace('_', ' '),
            'category': category or 'other',
            'summary': summary or '',
            'wiki_url': wiki_url,
            'wiki_title': wiki_title,
            'dynasty_context': dynasty_context or '',
            'added_by_work': work_id or '',
            'fetch_failed': summary is None,
        }

        # Store in DB
        self._store(entry)

        # Update mem cache
        self._mem_cache[term_zh] = entry

        if summary:
            logger.info(f"Cached historical ref: {term_zh} ({term_en}) — {len(summary)} chars")
        else:
            logger.warning(f"Wikipedia fetch failed for '{term_zh}' (tried '{wiki_title}')")

        return entry if not entry['fetch_failed'] else None

    def _store(self, entry: dict):
        """Write an entry to the DuckDB table."""
        try:
            conn = self._get_connection()
            self._ensure_table(conn)

            conn.execute(
                "INSERT OR REPLACE INTO historical_references "
                "(term_zh, term_py, term_en, category, summary, wiki_url, "
                "wiki_title, dynasty_context, added_by_work, added_at, fetch_failed) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    entry['term_zh'], entry.get('term_py', ''),
                    entry.get('term_en', ''), entry.get('category', 'other'),
                    entry.get('summary', ''), entry.get('wiki_url', ''),
                    entry.get('wiki_title', ''), entry.get('dynasty_context', ''),
                    entry.get('added_by_work', ''),
                    datetime.now(timezone.utc),
                    entry.get('fetch_failed', False),
                ]
            )
            conn.close()
        except Exception as e:
            logger.error(f"Failed to store historical ref '{entry['term_zh']}': {e}")

    def enrich_footnote(self, footnote: dict) -> dict:
        """If a footnote's ideogram is in the cache, append context to explanation.

        Only appends if the explanation doesn't already contain the cached info.
        Modifies in place and returns the footnote.
        """
        ideogram = footnote.get('ideogram', '')
        explanation = footnote.get('explanation', '')

        entry = self.get(ideogram)
        if not entry or not entry.get('summary'):
            return footnote

        # Don't duplicate if the summary content is already present
        summary_snippet = entry['summary'][:80]
        if summary_snippet[:40] in explanation:
            return footnote

        footnote['explanation'] = explanation.rstrip()
        if not footnote['explanation'].endswith('.'):
            footnote['explanation'] += '.'
        footnote['explanation'] += f" [{entry['summary']}]"

        if entry.get('wiki_url'):
            footnote.setdefault('wiki_url', entry['wiki_url'])

        return footnote

    def search(self, query: str) -> List[dict]:
        """Search cached terms by Chinese or English name (substring match)."""
        self._load_cache()
        results = []
        q = query.lower()
        for entry in self._mem_cache.values():
            if (q in entry.get('term_zh', '') or
                q in entry.get('term_en', '').lower() or
                q in entry.get('summary', '').lower()):
                results.append(entry)
        return results

    @property
    def count(self) -> int:
        self._load_cache()
        return len(self._mem_cache)

    def list_by_category(self, category: str) -> List[dict]:
        """List all cached terms in a category."""
        self._load_cache()
        return [e for e in self._mem_cache.values() if e.get('category') == category]

    def stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        self._load_cache()
        by_category: Dict[str, int] = {}
        failed = 0
        for entry in self._mem_cache.values():
            cat = entry.get('category', 'other')
            by_category[cat] = by_category.get(cat, 0) + 1
            if entry.get('fetch_failed'):
                failed += 1
        return {
            "total": len(self._mem_cache),
            "by_category": by_category,
            "fetch_failed": failed,
        }


_WIKI_MERGE_PROMPT = """You are editing footnotes for a translated Chinese novel. You will receive a footnote explanation and a Wikipedia summary about the same topic.

Your task: integrate any useful factual details from the Wikipedia summary into the existing explanation. Produce a single, fluent paragraph.

Rules:
- Keep the existing explanation's style and register
- Add specific dates, facts, or context from Wikipedia that the explanation lacks
- Do NOT duplicate information already in the explanation
- Do NOT add Wikipedia disclaimers or source attribution
- Do NOT change the tone — it should still read as a literary footnote, not an encyclopedia entry
- Keep the result concise (2-4 sentences max)
- If the Wikipedia summary adds nothing useful beyond what's already there, return the original explanation unchanged

Return ONLY the merged explanation text, nothing else."""


def _llm_merge_wiki_summaries(pending: list) -> int:
    """Use DeepSeek to cleanly merge Wikipedia summaries into footnote explanations.

    Args:
        pending: List of dicts with "fn" (footnote dict), "summary", "wiki_url".

    Returns:
        Number of footnotes successfully enriched.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    try:
        from utils.clients.llm_config import get_llm_client
        from utils.clients.llm_client import LLMRequest
        client = get_llm_client(provider="deepseek")
    except Exception as e:
        logger.warning(f"Cannot initialize LLM for wiki merge: {e}")
        # Fallback: simple append
        count = 0
        for item in pending:
            fn = item["fn"]
            expl = fn["explanation"].rstrip()
            if not expl.endswith("."):
                expl += "."
            fn["explanation"] = expl + f" ({item['summary'][:150]})"
            if item["wiki_url"]:
                fn["wiki_url"] = item["wiki_url"]
            count += 1
        return count

    def _merge_one(item):
        fn = item["fn"]
        try:
            response = client.chat(LLMRequest(
                messages=[
                    {"role": "system", "content": _WIKI_MERGE_PROMPT},
                    {"role": "user", "content": (
                        f"EXISTING EXPLANATION:\n{fn['explanation']}\n\n"
                        f"WIKIPEDIA SUMMARY:\n{item['summary']}"
                    )},
                ],
                model="deepseek-chat",
                temperature=0.2,
                max_tokens=300,
            ))
            merged = response.text.strip()
            if merged and len(merged) > 20:
                fn["explanation"] = merged
                if item["wiki_url"]:
                    fn["wiki_url"] = item["wiki_url"]
                return True
        except Exception as e:
            logger.debug(f"Wiki merge failed for {fn.get('ideogram', '?')}: {e}")
        return False

    enriched = 0
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(_merge_one, item): item for item in pending}
        for fut in as_completed(futures):
            if fut.result():
                enriched += 1

    return enriched


def enrich_work_footnotes(
    data: dict,
    work_id: str = "",
    db_path: Optional[Path] = None,
    max_summary_chars: int = 300,
) -> dict:
    """Post-translation enrichment: fetch Wikipedia summaries for footnotes.

    Iterates all footnotes in a translated work. For each footnote with a
    `wiki_title` that isn't already cached, fetches from Wikipedia and stores
    in DuckDB. Appends a brief summary to `footnote_explanation` and attaches
    `wiki_url` for source attribution.

    Runs **after cleanup stages** and **before validation** in pipeline_runner.

    Args:
        data: Full translated work dict (has body.chapters[].content_blocks[]).
        work_id: Work identifier for provenance tracking.
        db_path: Optional DuckDB path override.
        max_summary_chars: Max chars for appended Wikipedia summary (~300).

    Returns:
        The same data dict, modified in place.
    """
    cache = HistoricalRefCache(db_path=db_path)
    skipped_count = 0
    pending = []  # collect (fn, summary, wiki_url) for LLM merge

    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
    for chapter in chapters:
        for block in chapter.get("content_blocks", []):
            for fn in block.get("footnotes", []):
                ideogram = fn.get("ideogram", "")
                explanation = fn.get("explanation", "")
                pinyin = fn.get("pinyin", "")

                if not ideogram or not explanation:
                    continue

                # Extract an English search term from the explanation
                # Footnotes typically start with "The X" or "Name, the X"
                wiki_search = _extract_wiki_search_term(explanation, pinyin)
                if not wiki_search:
                    skipped_count += 1
                    continue

                entry = cache.get_or_fetch(
                    term_zh=ideogram,
                    wiki_title=wiki_search,
                    term_en=wiki_search,
                    term_py=pinyin,
                    work_id=work_id,
                )

                if not entry or not entry.get("summary"):
                    skipped_count += 1
                    continue

                # Only append if not already present (idempotent)
                summary = entry["summary"]
                if len(summary) > max_summary_chars:
                    cut = summary[:max_summary_chars]
                    last_period = cut.rfind(". ")
                    if last_period > max_summary_chars // 3:
                        summary = cut[:last_period + 1]
                    else:
                        summary = cut + "..."

                if summary[:40] in explanation:
                    continue  # Already enriched

                # Collect for LLM merge
                pending.append({
                    "fn": fn,
                    "summary": summary,
                    "wiki_url": entry.get("wiki_url", ""),
                })

    if not pending:
        logger.info(f"Wiki enrichment: 0 to enrich, {skipped_count} skipped")
        return data

    # Merge Wikipedia context into explanations via LLM (parallel)
    logger.info(f"Wiki enrichment: merging {len(pending)} footnotes via LLM...")
    enriched_count = _llm_merge_wiki_summaries(pending)

    logger.info(
        f"Wiki enrichment: {enriched_count} footnotes enriched, "
        f"{skipped_count} no wiki match, {cache.count} cached terms"
    )

    return data
