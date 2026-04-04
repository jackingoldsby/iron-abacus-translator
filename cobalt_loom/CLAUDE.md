# CLAUDE.md — Cobalt Loom (鈷織機)

Wikisource/ctext.org scraper for classical Chinese novels. Scrapes full text from web sources and emits JSON in the exact Jade Shuttle raw format, so Iron Abacus can process them identically to EPUB-extracted works.

**No LLMs** — purely deterministic scraping + structuring.

## Architecture

```
scrapers/       →  structurers/   →  catalog/
(fetch HTML)       (emit JSON)       (update DuckDB)
     ↑
  cache/
(disk cache)
```

1. **Scrapers** fetch content from Wikisource (MediaWiki API) or ctext.org (HTML scraping).
2. **Structurers** convert HTML to tag/content blocks and emit the raw JSON contract.
3. **Catalog** updates existing work entries (work_link, work_files) in DuckDB.
4. **Cache** stores fetched HTML on disk (~/.cobalt_loom/cache/) to avoid re-fetching.

## CLI Commands

```bash
cd cobalt_loom

# List works needing scraping
python -m cli.scrape list

# Dry run — discover chapters, no downloads
python -m cli.scrape scrape --work A005 --dry-run

# Scrape one work
python -m cli.scrape scrape --work A005

# Scrape all unscraped works
python -m cli.scrape scrape --all

# Resume (skip already-scraped chapters)
python -m cli.scrape scrape --work A005 --resume

# Ignore HTML cache
python -m cli.scrape scrape --work A005 --no-cache

# Show progress
python -m cli.scrape status
```

## Raw JSON Contract

Output matches `jade_shuttle/transformers/json_emitter.py` exactly:

```json
{
  "metadata": {"title": "書名", "creator": "作者", "language": "zh-Hant", "source": "wikisource", "publisher": null},
  "source": "wikisource:說岳全傳",
  "number_of_characters": 500000,
  "chapters": [{"title": "第一回 ...", "content": [{"tag": "p", "content": "..."}]}],
  "toc": [{"full_title": "第一回 ...", "chapter_ref": "chapter_0"}]
}
```

## Scraping Strategy

### Wikisource (primary)
- MediaWiki API (`action=parse`, `action=query&list=allpages`)
- Each chapter = separate wiki page: `TITLE/第一回`
- Rate limit: 2s between requests
- Proper User-Agent header

### ctext.org (fallback, via Nimble SDK)
- Uses **Nimble SDK** (`nimble-python`) for stealth extraction with `vx10` headless driver
- Anti-bot bypass for ctext.org's protections
- Rate limit: 3s between requests
- Falls back to direct httpx if Nimble is unavailable
- Only used for works not available on Wikisource
- API key: `NIMBLE_API_TOKEN` in `.env`

## Catalog Integration

Unlike Jade Shuttle (which creates new `works` rows), Cobalt Loom only **updates** existing works:
- Updates `works.work_link` with source URL
- Creates `work_files` entries for the JSON output
- Works are already registered (A005–A023) from the xlsx import

## URL Mapping

`config/work_urls.py` contains the static mapping from work_number to Wikisource/ctext page titles.
Hand-maintained because catalog titles may differ from wiki page titles.

## Output Location

`/Users/jacki/project_files/translation_project/work_individual_files/work_NNNN/`

## Key Design Principles

- **No LLMs** — purely deterministic scraping
- **No imports from other products** — communicates through JSON files and shared DuckDB
- **Rate-limited** — respects source site rate limits
- **Cached** — HTML responses cached to disk for re-runs
- **Resume-safe** — can skip already-scraped chapters
