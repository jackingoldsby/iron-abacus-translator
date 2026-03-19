#!/usr/bin/env python3
"""
Review and fix all catalog title/author translations using gpt-4.1-mini.

Sends batches of works to the model, asking it to:
1. Fix author romanizations to standard pinyin (consistent across all works)
2. Use established English titles where they exist (e.g. Jin Yong novels)
3. Provide good literary English titles for lesser-known works
4. Flag any issues

Updates the works_consensus_translations table with corrected values.
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
BATCH_SIZE = 40  # works per API call

SYSTEM_PROMPT = """You are a Chinese literature scholar specializing in wuxia (martial arts fiction).
You are reviewing English translations of Chinese book titles and author names from a catalog of ~640 wuxia novels.

For each work, provide the best English translation:

**AUTHOR NAMES:**
- Use standard pinyin romanization consistently (e.g. 金庸 = Jin Yong, not Jinyong)
- Use the MOST WELL-KNOWN English form for famous authors:
  - 金庸 → Jin Yong
  - 古龍 → Gu Long
  - 梁羽生 → Liang Yusheng
  - 倪匡 → Ni Kuang
  - 黃易 → Huang Yi
  - 臥龍生 → Wolong Sheng
  - 還珠樓主 → Huanzhu Louzhu (pen name meaning "Master of the Pearl-Returning Tower")
  - 溫瑞安 → Wen Ruian
  - 蕭逸 → Xiao Yi
- For compound author fields (A/B/C), romanize each name separated by " / "
- "Div" likely means "various/diverse authors" → use "Various Authors"

**BOOK TITLES:**
- Use the ESTABLISHED English title if one exists (especially for Jin Yong, Gu Long, Liang Yusheng):
  - 射鵰英雄傳 → The Legend of the Condor Heroes (NOT "Legend of the Shooting Eagle Heroes")
  - 神鵰俠侶 → The Return of the Condor Heroes
  - 倚天屠龍記 → The Heaven Sword and Dragon Saber
  - 天龍八部 → Demi-Gods and Semi-Devils
  - 鹿鼎記 → The Deer and the Cauldron
  - 笑傲江湖 → The Smiling, Proud Wanderer
  - 碧血劍 → Sword Stained with Royal Blood
  - 雪山飛狐 → Flying Fox of Snowy Mountain
  - 書劍恩仇錄 → The Book and the Sword
  - 俠客行 → Ode to Gallantry
  - 連城訣 → A Deadly Secret
  - 鴛鴦刀 → A Deadly Secret (the Mandarin Duck Sabres)
  - 白馬嘯西風 →Erta yang Memanah Rajawali (use: White Horse Neighing in the Western Wind)
  - 越女劍 → Sword of the Yue Maiden
  - 飛狐外傳 → Young Flying Fox
  - 七劍下天山 → Seven Swords from Mount Heaven (Liang Yusheng)
  - 萍蹤俠影錄 →Erta yang Memanah Rajawali → use: The Wandering Swordsman

- For "舊版" (old version) prefix: add "(Original Edition)" suffix
- For "新修版" (newly revised) prefix: add "(Revised Edition)" suffix
- For lesser-known works, translate the title literarily — make it sound like a wuxia novel title
- Avoid flat/awkward translations. "殺伐世家" should be something like "House of Slaughter" not "Killing the Family"
- "劫火紅蓮" → "Red Lotus of Tribulation" not "Tribulation of the Red Lotus"

Return JSON with a "results" key containing an array of ALL works:
{"results": [
  {
    "work_id": 123,
    "title_english": "The corrected English title",
    "author_english": "The corrected author name",
    "changed": true
  },
  {
    "work_id": 456,
    "title_english": "Unchanged title",
    "author_english": "Unchanged author",
    "changed": false
  }
]}

Only set "changed": true if you actually modified the title or author.
Return ALL works from input. No explanation, only JSON."""


def load_works():
    conn = connect_catalog(CATALOG_DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT w.work_id, w.work_number, w.title_chinese, w.author_chinese,
               COALESCE(wct.consensus_title_english, w.title_english, '') as title_en,
               COALESCE(wct.consensus_author_english, w.author_english, '') as author_en
        FROM works w
        LEFT JOIN works_consensus_translations wct ON w.work_id = wct.work_id
        ORDER BY w.author_chinese, w.title_chinese
    """)
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "work_id": r[0],
            "work_number": r[1],
            "title_chinese": r[2],
            "author_chinese": r[3],
            "title_english": r[4],
            "author_english": r[5],
        }
        for r in rows
    ]


def review_batch(client, works):
    """Send a batch of works to mini for review."""
    user_content = json.dumps(
        [
            {
                "work_id": w["work_id"],
                "title_chinese": w["title_chinese"],
                "author_chinese": w["author_chinese"],
                "current_title_english": w["title_english"],
                "current_author_english": w["author_english"],
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
        temperature=0.2,
        component="catalog_review",
    )

    # Handle both {"results": [...]} and [...] formats
    if isinstance(data, dict):
        # Find the first list value in the dict
        for key in ("results", "works", "translations", "data"):
            if key in data and isinstance(data[key], list):
                return data[key]
        # Fall back to first list value
        for v in data.values():
            if isinstance(v, list):
                return v
        # Dict keyed by work_id (e.g. {"123": {"title_english": ..., ...}})
        results = []
        for k, v in data.items():
            try:
                wid = int(k)
            except (ValueError, TypeError):
                continue
            if isinstance(v, dict):
                v["work_id"] = wid
                results.append(v)
        if results:
            return results
        # Single flat dict
        if "work_id" in data and "title_english" in data:
            return [data]
        raise ValueError(f"Unexpected response structure: {list(data.keys())}")

    return data


def update_db(corrections):
    """Update consensus translations in the database."""
    conn = connect_catalog(CATALOG_DB)
    cur = conn.cursor()

    updated = 0
    for c in corrections:
        if not c.get("changed", False):
            continue

        work_id = c["work_id"]
        title = c["title_english"]
        author = c["author_english"]

        # Check if consensus row exists
        cur.execute(
            "SELECT work_id FROM works_consensus_translations WHERE work_id = ?",
            (work_id,),
        )
        if cur.fetchone():
            cur.execute(
                """UPDATE works_consensus_translations
                   SET consensus_title_english = ?, consensus_author_english = ?,
                       title_rationale = 'Reviewed by gpt-4.1-mini',
                       author_rationale = 'Reviewed by gpt-4.1-mini',
                       searched_at = CURRENT_TIMESTAMP
                   WHERE work_id = ?""",
                (title, author, work_id),
            )
        else:
            cur.execute(
                """INSERT INTO works_consensus_translations
                   (work_id, consensus_title_english, consensus_author_english,
                    title_rationale, author_rationale, searched_at)
                   VALUES (?, ?, ?, 'Reviewed by gpt-4.1-mini', 'Reviewed by gpt-4.1-mini', CURRENT_TIMESTAMP)""",
                (work_id, title, author),
            )
        updated += 1

    conn.commit()
    conn.close()
    return updated


def main():
    works = load_works()
    print(f"Loaded {len(works)} works from catalog")

    # Process in batches
    all_corrections = []
    total_changed = 0

    for batch_start in range(0, len(works), BATCH_SIZE):
        batch = works[batch_start : batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(works) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"\nBatch {batch_num}/{total_batches} ({len(batch)} works)...")

        try:
            results = review_batch(None, batch)
            changed = sum(1 for r in results if r.get("changed", False))
            total_changed += changed
            all_corrections.extend(results)
            print(f"  -> {changed} corrections in this batch")

            # Show changes
            for r in results:
                if r.get("changed"):
                    wk = next((w for w in batch if w["work_id"] == r["work_id"]), None)
                    if wk:
                        changes = []
                        if r["title_english"] != wk["title_english"]:
                            changes.append(f'title: "{wk["title_english"]}" -> "{r["title_english"]}"')
                        if r["author_english"] != wk["author_english"]:
                            changes.append(f'author: "{wk["author_english"]}" -> "{r["author_english"]}"')
                        if changes:
                            print(f"     {wk['work_number']} {wk['title_chinese']}: {'; '.join(changes)}")

        except Exception as e:
            print(f"  ERROR: {e}")
            time.sleep(5)
            continue

        # Rate limit
        if batch_start + BATCH_SIZE < len(works):
            time.sleep(1)

    # Save corrections to JSON for review
    review_path = Path("translation_data/catalog_review.json")
    review_path.parent.mkdir(parents=True, exist_ok=True)
    with open(review_path, "w", encoding="utf-8") as f:
        json.dump(all_corrections, f, ensure_ascii=False, indent=2)
    print(f"\nSaved {len(all_corrections)} reviews to {review_path}")
    print(f"Total corrections: {total_changed}")

    # Ask before updating DB
    if total_changed > 0:
        if "--apply" in sys.argv:
            updated = update_db(all_corrections)
            print(f"Updated {updated} rows in database")
        else:
            print("\nRun with --apply to update the database")
            print(f"  python scripts/review_catalog_translations.py --apply")


if __name__ == "__main__":
    main()
