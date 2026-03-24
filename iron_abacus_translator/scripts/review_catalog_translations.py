#!/usr/bin/env python3
"""
Review and fix English title translations in the catalog database.

Uses canonical translations for well-known works, then GPT for the rest.
Updates both works_consensus_translations and works.title_english.

Usage:
    python scripts/review_catalog_translations.py                # Dry run (canonical only)
    python scripts/review_catalog_translations.py --apply        # Apply canonical fixes
    python scripts/review_catalog_translations.py --apply --gpt  # Also re-translate bad titles via GPT
"""

import sys
import json
import re
import argparse
import logging
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.db import connect_catalog

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Canonical English translations for well-known works.
CANONICAL = {
    # Jin Yong (金庸) — 15 novels
    "射鵰英雄傳": "The Legend of the Condor Heroes",
    "神鵰俠侶": "The Return of the Condor Heroes",
    "倚天屠龍記": "The Heaven Sword and Dragon Saber",
    "天龍八部": "Demi-Gods and Semi-Devils",
    "笑傲江湖": "The Smiling, Proud Wanderer",
    "鹿鼎記": "The Deer and the Cauldron",
    "書劍恩仇錄": "The Book and the Sword",
    "碧血劍": "Sword Stained with Royal Blood",
    "雪山飛狐": "Flying Fox of Snowy Mountain",
    "飛狐外傳": "Young Flying Fox",
    "俠客行": "Ode to Gallantry",
    "連城訣": "A Deadly Secret",
    "鴛鴦刀": "Mandarin Duck Blades",
    "白馬嘯西風": "White Horse in the Western Wind",
    "越女劍": "Sword of the Yue Maiden",
    "素心劍": "Sword of the Pure Heart",
    # Liang Yusheng (梁羽生) — major works
    "白髮魔女傳": "The White-Haired Demoness",
    "七劍下天山": "Seven Swords of Mount Heaven",
    "萍蹤俠影錄": "Duckweed Trace, Hero's Shadow",
    "雲海玉弓緣": "Jade Bow in the Sea of Clouds",
    "大唐遊俠傳": "Knights-Errant of the Tang Dynasty",
    "冰川天女傳": "The Ice-River Heavenly Maiden",
    "還劍奇情錄": "The Returned Sword",
    "散花女俠": "The Flower-Scattering Heroine",
    "聯劍風雲錄": "Chronicle of the United Swords",
    "廣陵劍": "The Guangling Sword",
    "武林天驕": "Pride of the Martial World",
    "飛鳳潛龍": "The Hidden Dragon and Soaring Phoenix",
    "狂俠天驕魔女": "The Wild Hero, the Proud Lord, and the Demoness",
    "鳴鏑風雲錄": "Chronicle of the Whistling Arrow",
    "風雷震九州": "Thunder and Lightning Across Nine Provinces",
    "俠骨丹心": "Chivalrous Bones, Loyal Heart",
    "瀚海雄風": "Winds of the Desert Sea",
    "遊劍江湖": "Wandering Swordsman of the Jianghu",
    "牧野流星": "Shooting Stars over the Pastures",
    "彈指驚雷": "Thunder at a Snap of the Fingers",
    "絕塞傳烽錄": "Beacon Fires at the Frontier Pass",
    "劍網塵絲": "Sword-Net and Gossamer Threads",
    "幻劍靈旗": "Phantom Swords and Spirit Banners",
    "慧劍心魔": "The Wisdom Sword and the Heart's Demon",
    "武林三絕": "Three Marvels of the Martial World",
    "武當一劍": "One Sword of Wudang",
    # Gu Long (古龍) — major works
    "絕代雙驕": "Peerless Twins",
    "多情劍客無情劍": "The Sentimental Swordsman, the Ruthless Sword",
    "楚留香傳奇": "The Legend of Chu Liuxiang",
    "陸小鳳傳奇": "The Legend of Lu Xiaofeng",
    "天涯明月刀": "Horizon, Bright Moon, Saber",
    "流星蝴蝶劍": "Meteor, Butterfly, Sword",
    "七種武器": "Seven Weapons",
    "歡樂英雄": "The Merry Hero",
    "大旗英雄傳": "Heroes of the Great Banner",
    "浣花洗劍錄": "Cleansing the Sword at Huanhua Creek",
    "武林外史": "Tales Outside the Martial World",
    "蕭十一郎": "Xiao Shiyi Lang",
    "大人物": "The Big Shot",
    "邊城浪子": "The Wanderer of the Frontier",
    "九月鷹飛": "September Eagle Flies",
    "三少爺的劍": "The Third Young Master's Sword",
    "白玉老虎": "The White Jade Tiger",
    "圓月彎刀": "Full Moon Scimitar",
    "飛刀又見飛刀": "Flying Daggers Seen Again",
    "劍花煙雨江南": "Sword Blossoms, Misty Rain, Jiangnan",
    "血鸚鵡": "The Blood Parrot",
    "碧玉刀": "The Jade Saber",
    "孔雀翎": "The Peacock Plume",
    "離別鉤": "The Parting Hook",
    "長生劍": "The Longevity Sword",
    "霸王槍": "The Hegemon Spear",
    "拳頭": "The Fist",
    "英雄無淚": "Heroes Without Tears",
}

VERSION_PREFIXES = {"舊版": "Original Edition", "新修版": "Revised Edition"}


def strip_version_prefix(title_chinese: str) -> tuple[str, str]:
    """Return (base_title, edition) stripping 舊版/新修版."""
    for prefix_zh, edition in VERSION_PREFIXES.items():
        if title_chinese and title_chinese.startswith(prefix_zh):
            return title_chinese[len(prefix_zh):], edition
    return title_chinese or "", ""


def needs_fix(title_english: str) -> bool:
    """Return True if the English title likely needs improvement."""
    if not title_english:
        return True
    if re.search(r'[\u4e00-\u9fff]', title_english):
        return True
    # Pure pinyin with no English articles
    words = title_english.split()
    if len(words) <= 3:
        pinyin_like = sum(1 for w in words if re.match(r'^[A-Z][a-z]+$', w))
        if pinyin_like >= max(1, len(words) * 0.6):
            return True
    return False


def translate_title_batch(titles: list[tuple[str, str]], model="gpt-4.1-mini") -> dict[str, str]:
    """Use GPT to translate Chinese novel titles to English."""
    from openai import OpenAI
    client = OpenAI()

    title_list = "\n".join(f"{wn}: {tc}" for wn, tc in titles)

    response = client.chat.completions.create(
        model=model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a literary translator specializing in Chinese wuxia (martial arts) fiction. "
                    "Translate the following Chinese novel titles into evocative, publishable English titles.\n\n"
                    "Guidelines:\n"
                    "- 魔女 = 'Demoness', not 'Witch'\n"
                    "- 俠 = 'hero/knight-errant'\n"
                    "- 劍 = 'sword', 刀 = 'saber/blade'\n"
                    "- 江湖 = 'jianghu' or 'the martial world'\n"
                    "- Preserve poetic quality\n"
                    "- Character names stay in pinyin\n"
                    "- Do NOT include version/edition prefixes\n\n"
                    "Return JSON: {\"work_number\": \"English Title\", ...}"
                ),
            },
            {"role": "user", "content": f"Translate these titles:\n\n{title_list}"},
        ],
    )
    return json.loads(response.choices[0].message.content)


def main():
    parser = argparse.ArgumentParser(description="Review and fix catalog title translations")
    parser.add_argument("--apply", action="store_true", help="Apply fixes to database")
    parser.add_argument("--gpt", action="store_true", help="Also use GPT for non-canonical bad titles")
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--model", default="gpt-4.1-mini")
    args = parser.parse_args()

    conn = connect_catalog()
    rows = conn.execute("""
        SELECT w.work_id, w.work_number, w.title_chinese,
               COALESCE(wct.consensus_title_english, w.title_english, '') as title_en
        FROM works w
        LEFT JOIN works_consensus_translations wct ON w.work_id = wct.work_id
        ORDER BY w.work_number
    """).fetchall()

    updates = {}  # work_id -> new_title_english

    # Pass 1: Apply canonical translations
    canonical_count = 0
    for work_id, wn, tc, te in rows:
        base_title, _ = strip_version_prefix(tc or "")
        if base_title in CANONICAL:
            canonical = CANONICAL[base_title]
            if te != canonical:
                updates[work_id] = canonical
                canonical_count += 1

    logger.info(f"Canonical fixes needed: {canonical_count}")

    # Pass 2: GPT for remaining bad titles
    if args.gpt:
        needs_gpt = []
        for work_id, wn, tc, te in rows:
            if work_id in updates:
                continue
            base_title, _ = strip_version_prefix(tc or "")
            if base_title in CANONICAL:
                continue  # Already has a canonical translation
            if needs_fix(te):
                needs_gpt.append((work_id, wn, base_title))

        logger.info(f"Titles needing GPT: {len(needs_gpt)}")

        for i in range(0, len(needs_gpt), args.batch_size):
            batch = needs_gpt[i : i + args.batch_size]
            batch_for_gpt = [(wn, bt) for _, wn, bt in batch]
            id_map = {wn: wid for wid, wn, _ in batch}

            logger.info(f"GPT batch {i // args.batch_size + 1} ({len(batch)} titles)...")
            try:
                results = translate_title_batch(batch_for_gpt, model=args.model)
                for wn, new_title in results.items():
                    if new_title and wn in id_map:
                        updates[id_map[wn]] = new_title
            except Exception as e:
                logger.error(f"GPT batch failed: {e}")

            if i + args.batch_size < len(needs_gpt):
                time.sleep(1)

    # Report
    if not updates:
        logger.info("No updates needed!")
        return 0

    current = {work_id: (wn, tc, te) for work_id, wn, tc, te in rows}

    logger.info(f"\n{'='*80}")
    logger.info(f"PROPOSED UPDATES ({len(updates)} titles)")
    logger.info(f"{'='*80}")
    for work_id in sorted(updates.keys()):
        wn, tc, old = current[work_id]
        new = updates[work_id]
        print(f"  {wn:8s} {tc or '':24s} {old:45s} -> {new}")

    if args.apply:
        logger.info(f"\nApplying {len(updates)} updates...")
        for work_id, new_title in updates.items():
            # Update consensus table
            existing = conn.execute(
                "SELECT work_id FROM works_consensus_translations WHERE work_id = ?",
                (work_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE works_consensus_translations SET consensus_title_english = ? WHERE work_id = ?",
                    (new_title, work_id),
                )
            else:
                conn.execute(
                    """INSERT INTO works_consensus_translations (work_id, consensus_title_english)
                       VALUES (?, ?)""",
                    (work_id, new_title),
                )
            # Also update works.title_english for backward compat
            conn.execute(
                "UPDATE works SET title_english = ? WHERE work_id = ?",
                (new_title, work_id),
            )
        logger.info("Done!")
    else:
        logger.info(f"\nDry run — use --apply to write changes.")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
