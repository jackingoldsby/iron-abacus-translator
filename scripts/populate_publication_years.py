#!/usr/bin/env python3
"""
Populate publication_year for all works using gpt-4.1-mini.

For each work, asks mini to identify the ORIGINAL publication year
of the novel (first serialization or first book edition), not later
revised editions.

For authors like Jin Yong who have multiple editions (original 連載版,
revised 修訂版, new revised 新修版), we want the ORIGINAL publication year.

For "舊版" (old version) and "新修版" (newly revised) variants, still
record the original novel's first publication year.

Updates works.publication_year in the database.
"""

import json
import os
from utils.db import connect_catalog
import sys
import time
from pathlib import Path

from utils.clients import llm_chat_json

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.environment_config import get_or_create_config
CATALOG_DB = get_or_create_config().catalog_path
BATCH_SIZE = 50

SYSTEM_PROMPT = """You are a Chinese literature historian specializing in wuxia (martial arts fiction).

For each work, provide the ORIGINAL publication year — the year the novel was FIRST published
or serialized, NOT the year of a later revised edition.

Important notes:
- For Jin Yong (金庸) novels: use the year of FIRST serialization in newspapers/magazines.
  For example:
  - 射鵰英雄傳 → 1957 (serialized in Hong Kong Commercial Daily)
  - 神鵰俠侶 → 1959
  - 倚天屠龍記 → 1961
  - 天龍八部 → 1963
  - 笑傲江湖 → 1967
  - 鹿鼎記 → 1969
  - 書劍恩仇錄 → 1955 (his first novel)
  - 碧血劍 → 1956
  - 雪山飛狐 → 1959
  - 飛狐外傳 → 1960
  - 連城訣 → 1963
  - 俠客行 → 1965
  - 白馬嘯西風 → 1961
  - 鴛鴦刀 → 1961
  - 越女劍 → 1970
  - "舊版" (old version) or "新修版" (newly revised) variants should still use the original year

- For Gu Long (古龍): use first publication/serialization year
  - 多情劍客無情劍 → 1969
  - 絕代雙驕 → 1966
  - 楚留香傳奇 → 1967
  - 陸小鳳傳奇 → 1972
  - 小李飛刀 → 1969
  - 天涯明月刀 → 1974

- For Liang Yusheng (梁羽生): use first serialization year
  - 七劍下天山 → 1956
  - 白髮魔女傳 → 1957
  - 萍蹤俠影錄 → 1959
  - 雲海玉弓緣 → 1961

- For less famous authors/works, provide your best estimate. If truly unknown, use 0.

Return JSON with a "results" key containing an array:
{"results": [
  {"work_id": 123, "publication_year": 1957},
  {"work_id": 456, "publication_year": 0}
]}

Use 0 for unknown years. Return ALL works from the input, one entry per work."""


def load_works():
    conn = connect_catalog(CATALOG_DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT work_id, work_number, title_chinese, author_chinese,
               publication_year
        FROM works
        ORDER BY author_chinese, title_chinese
    """)
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "work_id": r[0],
            "work_number": r[1],
            "title_chinese": r[2],
            "author_chinese": r[3],
            "current_year": r[4],
        }
        for r in rows
    ]


def lookup_batch(client, works):
    user_content = json.dumps(
        [
            {
                "work_id": w["work_id"],
                "title_chinese": w["title_chinese"],
                "author_chinese": w["author_chinese"],
            }
            for w in works
        ],
        ensure_ascii=False,
        indent=2,
    )

    data = llm_chat_json(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        model="gpt-4.1-mini",
        temperature=0.1,
        component="publication_years",
    )

    if isinstance(data, dict):
        # Check for known list wrapper keys
        for key in ("results", "works", "data", "publications"):
            if key in data and isinstance(data[key], list):
                return data[key]
        # Find the first list value
        for v in data.values():
            if isinstance(v, list):
                return v
        # Model returned a dict keyed by work_id (e.g. {"123": {"publication_year": 1957}, ...})
        # or keyed by string work_id with year values (e.g. {"123": 1957, ...})
        results = []
        for k, v in data.items():
            if k == "error":
                continue
            try:
                wid = int(k)
            except (ValueError, TypeError):
                continue
            if isinstance(v, dict):
                results.append({"work_id": wid, "publication_year": v.get("publication_year", 0)})
            elif isinstance(v, int):
                results.append({"work_id": wid, "publication_year": v})
        if results:
            return results
        # Single flat dict like {"work_id": 123, "publication_year": 1957}
        if "work_id" in data and "publication_year" in data:
            return [data]
        raise ValueError(f"Unexpected response structure: {list(data.keys())}")

    return data


def update_db(results):
    conn = connect_catalog(CATALOG_DB)
    cur = conn.cursor()
    updated = 0
    for r in results:
        year = r.get("publication_year", 0)
        if year and year > 0:
            cur.execute(
                "UPDATE works SET publication_year = ? WHERE work_id = ?",
                (year, r["work_id"]),
            )
            updated += 1
    conn.commit()
    conn.close()
    return updated


def main():
    works = load_works()

    # Only process works without a year
    to_process = [w for w in works if not w["current_year"]]
    print(f"Total works: {len(works)}, need year: {len(to_process)}")

    if not to_process:
        print("All works already have publication years.")
        return

    all_results = []
    for batch_start in range(0, len(to_process), BATCH_SIZE):
        batch = to_process[batch_start : batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(to_process) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"\nBatch {batch_num}/{total_batches} ({len(batch)} works)...")

        try:
            results = lookup_batch(None, batch)
            years_found = sum(1 for r in results if r.get("publication_year", 0) > 0)
            all_results.extend(results)
            print(f"  -> {years_found} years identified")

            # Show some results
            for r in results[:5]:
                wk = next((w for w in batch if w["work_id"] == r["work_id"]), None)
                if wk and r.get("publication_year", 0) > 0:
                    print(f"     {wk['title_chinese']} ({wk['author_chinese']}) -> {r['publication_year']}")

        except Exception as e:
            print(f"  ERROR: {e}")
            time.sleep(5)
            continue

        if batch_start + BATCH_SIZE < len(to_process):
            time.sleep(1)

    # Save to JSON for review
    review_path = Path("translation_data/publication_years.json")
    review_path.parent.mkdir(parents=True, exist_ok=True)
    with open(review_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    total_found = sum(1 for r in all_results if r.get("publication_year", 0) > 0)
    print(f"\nTotal years found: {total_found}/{len(to_process)}")
    print(f"Saved to {review_path}")

    if "--apply" in sys.argv:
        updated = update_db(all_results)
        print(f"Updated {updated} rows in database")
    else:
        print("\nRun with --apply to update the database")


if __name__ == "__main__":
    main()
