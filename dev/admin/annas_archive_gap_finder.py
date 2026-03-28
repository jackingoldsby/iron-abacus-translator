#!/usr/bin/env python3
"""
Anna's Archive Gap Finder

Cross-references the works catalog against Anna's Archive search results
to identify downloadable EPUB files for works NOT already in the catalog.

Usage:
    python dev/admin/annas_archive_gap_finder.py
    python dev/admin/annas_archive_gap_finder.py --author "溫瑞安"
    python dev/admin/annas_archive_gap_finder.py --collections-only
    python dev/admin/annas_archive_gap_finder.py --output /tmp/download_list.json

Requires: nimble CLI (npm i -g @nimble-way/nimble-cli)
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Resolve paths
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "iron_abacus_translator"))

import duckdb

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DB_PATH = "/Users/jacki/project_files/translation_project/db/works_translator.duckdb"
ANNAS_ARCHIVE_BASE = "https://annas-archive.gl"

# Authors with known gaps — traditional + simplified variants
TARGET_AUTHORS = {
    "溫瑞安": {"simplified": "温瑞安", "english": "Wen Ruian"},
    "蕭逸": {"simplified": "萧逸", "english": "Xiao Yi"},
    "陳青雲": {"simplified": "陈青云", "english": "Chen Qingyun"},
    "柳殘陽": {"simplified": "柳残阳", "english": "Liu Canyang"},
    "臥龍生": {"simplified": "卧龙生", "english": "Wolong Sheng"},
    "司馬翎": {"simplified": "司马翎", "english": "Sima Ling"},
    "黃易": {"simplified": "黄易", "english": "Huang Yi"},
    "梁羽生": {"simplified": "梁羽生", "english": "Liang Yusheng"},
}


@dataclass
class ArchiveResult:
    """A single result from Anna's Archive."""
    title: str
    md5_url: str
    is_collection: bool = False
    estimated_book_count: int = 1
    format_hint: str = ""
    size_hint: str = ""


@dataclass
class AuthorGapReport:
    """Gap analysis for a single author."""
    author_chinese: str
    author_simplified: str
    author_english: str
    catalog_count: int
    catalog_titles: List[str]
    archive_individual: List[ArchiveResult]
    archive_collections: List[ArchiveResult]
    new_titles_found: List[str]  # titles in archive but NOT in catalog


def get_catalog_works(con: duckdb.DuckDBPyConnection) -> Dict[str, List[str]]:
    """Get all works grouped by author (both trad and simplified)."""
    rows = con.execute(
        "SELECT author_chinese, title_chinese FROM works ORDER BY author_chinese"
    ).fetchall()

    by_author: Dict[str, List[str]] = {}
    for author, title in rows:
        by_author.setdefault(author, []).append(title)
    return by_author


def search_annas_archive(query: str, max_retries: int = 2) -> List[ArchiveResult]:
    """Search Anna's Archive via nimble extract and parse results."""
    url = f"{ANNAS_ARCHIVE_BASE}/search?q={query}&lang=zh&content=book_fiction&ext=epub"

    for attempt in range(max_retries + 1):
        try:
            result = subprocess.run(
                ["nimble", "extract", "--url", url],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                logger.warning(f"  nimble failed (attempt {attempt+1}): {result.stderr[:200]}")
                if attempt < max_retries:
                    time.sleep(2)
                continue

            data = json.loads(result.stdout)
            html = data.get("data", {}).get("html", "")

            # Parse md5 links and titles
            pattern = r'<a[^>]*href="(/md5/[^"]+)"[^>]*>(.*?)</a>'
            matches = re.findall(pattern, html)

            results = []
            seen = set()
            for href, raw_title in matches:
                title = re.sub(r'<[^>]+>', '', raw_title).strip()
                if not title or title in seen:
                    continue
                seen.add(title)

                # Detect collections
                is_collection = False
                book_count = 1
                count_match = re.search(r'(\d+)\s*[册冊部]', title)
                if count_match:
                    book_count = int(count_match.group(1))
                    if book_count > 1:
                        is_collection = True

                if any(kw in title for kw in ['全集', '合辑', '合集', '作品集', '套装', '套裝']):
                    is_collection = True
                    if book_count == 1:
                        book_count = 0  # unknown

                results.append(ArchiveResult(
                    title=title,
                    md5_url=f"{ANNAS_ARCHIVE_BASE}{href}",
                    is_collection=is_collection,
                    estimated_book_count=book_count,
                ))

            return results

        except subprocess.TimeoutExpired:
            logger.warning(f"  nimble timeout (attempt {attempt+1})")
            if attempt < max_retries:
                time.sleep(2)
        except json.JSONDecodeError:
            logger.warning(f"  JSON parse error (attempt {attempt+1})")
            if attempt < max_retries:
                time.sleep(2)

    return []


def title_matches_catalog(archive_title: str, catalog_titles: List[str]) -> bool:
    """Check if an archive title matches any catalog title (fuzzy)."""
    # Normalize: remove punctuation, spaces
    def normalize(t: str) -> str:
        t = re.sub(r'[（()）\[\]【】《》\s·．.、，,]', '', t)
        return t.lower()

    archive_norm = normalize(archive_title)

    for cat_title in catalog_titles:
        cat_norm = normalize(cat_title)
        # Exact match
        if archive_norm == cat_norm:
            return True
        # One contains the other
        if len(cat_norm) >= 2 and (cat_norm in archive_norm or archive_norm in cat_norm):
            return True

    return False


def is_wuxia_relevant(title: str) -> bool:
    """Filter out non-wuxia results (false positives from search)."""
    # Exclude obvious non-wuxia
    exclude_patterns = [
        r'武俠世界.*第.*期',  # Magazine issues
        r'連載插畫版',  # Serialized illustration versions
        r'联合创作',  # Collaborative serials
        r'Oracle|SQL|数据库|教程',  # Tech books
        r'少年文学|童话',  # Children's literature
        r'民主|政治|经济',  # Politics/economics
        r'柳宗悦|柳是',  # Wrong 柳 author
        r'战神联盟|混沌帝君',  # Xianxia/webnovels
    ]
    for pat in exclude_patterns:
        if re.search(pat, title):
            return False
    return True


def analyze_author(
    author_trad: str,
    author_info: dict,
    catalog_works: Dict[str, List[str]],
) -> AuthorGapReport:
    """Analyze gaps for one author."""
    simplified = author_info["simplified"]
    english = author_info["english"]

    # Get catalog titles (check both trad and simplified)
    catalog_titles = catalog_works.get(author_trad, []) + catalog_works.get(simplified, [])
    catalog_titles = list(set(catalog_titles))

    logger.info(f"\n{'='*60}")
    logger.info(f"  {author_trad} ({english}) — {len(catalog_titles)} works in catalog")
    logger.info(f"{'='*60}")

    # Search Anna's Archive with both name variants
    all_results: List[ArchiveResult] = []
    seen_urls = set()

    for name_variant in [author_trad, simplified]:
        logger.info(f"  Searching: {name_variant} epub ...")
        results = search_annas_archive(f"{name_variant} epub")
        for r in results:
            if r.md5_url not in seen_urls:
                seen_urls.add(r.md5_url)
                all_results.append(r)
        time.sleep(1)  # Rate limit

    # Also search for collections specifically
    for name_variant in [simplified]:  # Simplified more common on Anna's
        logger.info(f"  Searching: {name_variant} 全集 ...")
        results = search_annas_archive(f"{name_variant} 全集")
        for r in results:
            if r.md5_url not in seen_urls:
                seen_urls.add(r.md5_url)
                all_results.append(r)
        time.sleep(1)

    # Filter to wuxia-relevant results
    all_results = [r for r in all_results if is_wuxia_relevant(r.title)]

    # Separate collections from individual works
    collections = [r for r in all_results if r.is_collection]
    individuals = [r for r in all_results if not r.is_collection]

    # Find NEW titles (not in catalog)
    new_titles = []
    for r in individuals:
        if not title_matches_catalog(r.title, catalog_titles):
            new_titles.append(r.title)

    logger.info(f"  Found: {len(collections)} collections, {len(individuals)} individual works")
    logger.info(f"  New (not in catalog): {len(new_titles)} individual titles")

    if collections:
        logger.info(f"  Collections:")
        for c in collections:
            count_str = f" ({c.estimated_book_count} books)" if c.estimated_book_count > 1 else ""
            logger.info(f"    📦 {c.title}{count_str}")
            logger.info(f"       {c.md5_url}")

    if new_titles:
        logger.info(f"  New individual titles:")
        for t in new_titles[:15]:
            logger.info(f"    📖 {t}")
        if len(new_titles) > 15:
            logger.info(f"    ... and {len(new_titles) - 15} more")

    return AuthorGapReport(
        author_chinese=author_trad,
        author_simplified=simplified,
        author_english=english,
        catalog_count=len(catalog_titles),
        catalog_titles=catalog_titles,
        archive_individual=[r for r in individuals],
        archive_collections=collections,
        new_titles_found=new_titles,
    )


def generate_download_list(reports: List[AuthorGapReport]) -> dict:
    """Generate a structured download list from gap reports."""
    download_list = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {},
        "recommended_downloads": [],
        "all_results": [],
    }

    total_new = 0
    for report in reports:
        total_new += len(report.new_titles_found)
        download_list["summary"][report.author_chinese] = {
            "in_catalog": report.catalog_count,
            "collections_available": len(report.archive_collections),
            "new_individual_titles": len(report.new_titles_found),
        }

        # Recommend collections first (best bang for buck)
        for c in report.archive_collections:
            download_list["recommended_downloads"].append({
                "priority": "HIGH",
                "type": "collection",
                "author": report.author_chinese,
                "title": c.title,
                "url": c.md5_url,
                "estimated_books": c.estimated_book_count,
            })

        # Then individual new titles
        for r in report.archive_individual:
            if r.title in report.new_titles_found:
                download_list["all_results"].append({
                    "type": "individual",
                    "author": report.author_chinese,
                    "title": r.title,
                    "url": r.md5_url,
                    "in_catalog": False,
                })

    download_list["summary"]["_total_new_titles"] = total_new
    return download_list


def main():
    parser = argparse.ArgumentParser(description="Find missing wuxia works on Anna's Archive")
    parser.add_argument("--author", help="Analyze single author (Chinese name)")
    parser.add_argument("--collections-only", action="store_true", help="Only show collections")
    parser.add_argument("--output", "-o", help="Output JSON path (default: stdout summary)")
    args = parser.parse_args()

    # Verify nimble is available
    try:
        subprocess.run(["nimble", "--version"], capture_output=True, timeout=5)
    except FileNotFoundError:
        logger.error("nimble CLI not found. Install: npm i -g @nimble-way/nimble-cli")
        return 1

    # Load catalog
    con = duckdb.connect(DB_PATH, read_only=True)
    catalog_works = get_catalog_works(con)
    con.close()

    total_catalog = sum(len(v) for v in catalog_works.values())
    logger.info(f"Catalog: {total_catalog} works across {len(catalog_works)} authors")

    # Select authors to analyze
    if args.author:
        # Find matching author
        matched = None
        for trad, info in TARGET_AUTHORS.items():
            if args.author in (trad, info["simplified"], info["english"]):
                matched = (trad, info)
                break
        if not matched:
            logger.error(f"Unknown author: {args.author}")
            logger.info(f"Known authors: {', '.join(TARGET_AUTHORS.keys())}")
            return 1
        authors_to_check = {matched[0]: matched[1]}
    else:
        authors_to_check = TARGET_AUTHORS

    # Analyze each author
    reports: List[AuthorGapReport] = []
    for author_trad, author_info in authors_to_check.items():
        report = analyze_author(author_trad, author_info, catalog_works)
        reports.append(report)

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"  SUMMARY")
    logger.info(f"{'='*60}")
    for r in reports:
        logger.info(
            f"  {r.author_chinese} ({r.author_english}): "
            f"{r.catalog_count} in catalog, "
            f"{len(r.archive_collections)} collections, "
            f"{len(r.new_titles_found)} new individual titles"
        )

    # Output
    if args.output:
        download_list = generate_download_list(reports)
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(download_list, f, ensure_ascii=False, indent=2)
        logger.info(f"\nDownload list saved to: {output_path}")
        logger.info(f"Recommended downloads: {len(download_list['recommended_downloads'])}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
