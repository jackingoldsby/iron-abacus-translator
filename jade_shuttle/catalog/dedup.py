"""Catalog deduplication — load catalog and match titles."""

import re
from typing import Dict, List, Optional, Set, Tuple

import duckdb

from transformers.encoding import S2T, T2S


def normalize_title(t: str) -> str:
    """Normalize a title for comparison."""
    t = re.sub(r"[（()）\[\]【】《》\s·．.、，,：:\"\"''「」]", "", t)
    return t.lower()


def load_catalog(db_path: str) -> Tuple[List[Dict], Set[str]]:
    """Load works and authors from catalog.

    Returns (works_list, author_names_set).
    """
    con = duckdb.connect(db_path, read_only=True)
    rows = con.execute(
        "SELECT work_id, work_number, title_chinese, author_chinese, title_author, directory_number "
        "FROM works"
    ).fetchall()
    works = []
    authors = set()
    for r in rows:
        works.append({
            "work_id": r[0],
            "work_number": r[1],
            "title_chinese": r[2],
            "author_chinese": r[3],
            "title_author": r[4],
            "directory_number": r[5],
        })
        if r[3]:
            authors.add(r[3])
    con.close()
    return works, authors


def title_matches_catalog(
    work_title: str,
    catalog_works: List[Dict],
    author_trad: str = "",
    author_simp: str = "",
) -> Optional[Dict]:
    """Check if a work title matches any catalog entry.

    Returns the matched catalog work dict or None.
    """
    norm_title = normalize_title(work_title)
    if len(norm_title) < 2:
        return None

    title_variants = {norm_title}
    title_variants.add(normalize_title(S2T.convert(work_title)))
    title_variants.add(normalize_title(T2S.convert(work_title)))

    for cat_work in catalog_works:
        cat_title = cat_work.get("title_chinese", "") or ""
        cat_author = cat_work.get("author_chinese", "") or ""
        cat_norm = normalize_title(cat_title)

        if len(cat_norm) < 2:
            continue

        author_match = True
        if author_trad and cat_author:
            author_match = cat_author in (author_trad, author_simp)

        if not author_match:
            continue

        for variant in title_variants:
            if variant == cat_norm:
                return cat_work
            if len(cat_norm) >= 2 and len(variant) >= 2:
                if cat_norm in variant or variant in cat_norm:
                    return cat_work

    return None
