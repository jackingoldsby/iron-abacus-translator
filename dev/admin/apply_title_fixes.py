#!/usr/bin/env python3
"""
Apply curated title_english fixes from enrichment review.
Only updates titles that are clear wins: established translations, fixed pinyin, corrected idioms.

Usage:
    python dev/admin/apply_title_fixes.py --dry-run
    python dev/admin/apply_title_fixes.py
"""

import duckdb
import sys
from pathlib import Path

DB_PATH = Path.home() / "project_files" / "translation_project" / "db" / "works_translator.duckdb"

# Curated fixes: current_title -> new_title
TITLE_FIXES = {
    # Established canonical translations
    "Dragon Babu": "Demi-Gods and Semi-Devils",
    "Sentimental Prodigal Son": "The Sentimental Swordsman and the Ruthless Sword",
    "Peerless Twins": "The Legendary Twins",
    "Swordsman": "The Smiling, Proud Wanderer",
    "Book, Sword and Enmity": "The Book and the Sword",
    "Blue Blood Sword": "Sword Stained with Royal Blood",
    "Flying Fox of Snowy Mountain": "Fox Volant of the Snowy Mountain",
    "The Flower-Guarding Bell": "The Handsome Siblings",
    "Xiao Shiyi Lang": "The Eleventh Son",
    "The Legend of Heaven and Dragon Sword": "The Heaven Sword and Dragon Saber",

    # Fixed untranslated pinyin
    "Jiangxue Xuanshuang": "Crimson Snow and Dark Frost",
    "Ma Ming Feng": "The Song of the Horse and the Whisper of the Wind",
    "Feng Wu Jiu Tian": "Phoenix Dances in the Ninth Heaven",
    "Fengyun Leiden": "Wind, Cloud, Thunder, and Lightning",
    "Qionghai Tengjiao": "The Dragon Soars in the Jade Sea",
    "Han Xing Leng Yue Qiu": "Vendetta Under a Cold Star and Icy Moon",
    "Wulin Zhengqi Song": "Song of Righteousness in the Martial World",
    "Changhong Pass Japan": "Rainbow Piercing the Sun",

    # Fixed mistranslations / mangled idioms
    "A Sword Hangs the Liver and Gallbladder": "A Sword Tests the Courage",
    "The Nameless Xiao": "The Nameless Flute",
    "The Six-Fingered Qin Demon": "The Six-Fingered Zither Demon",
    "The Murderer Tang Zhan": "The Assassin Tang Zhan",

    # Fixed mistranslation (神鵰俠侶 is the sequel, not 射鵰英雄傳)
    # D56 handled by work_number override below

    # Old version naming convention — D301 handled by work_number override below
    "Old version of Blue Blood Sword": "Sword Stained with Royal Blood (Original Serialized Version)",
    "Old version of Book of Swords and Enmities": "The Book and the Sword (Original Serialized Version)",
    "Old version of Snow Mountain Feihu": "Fox Volant of the Snowy Mountain (Original Serialized Version)",
    "Old version of Swordsman": "The Smiling, Proud Wanderer (Original Serialized Version)",
    "Old version of Tian Long Ba Bu": "Demi-Gods and Semi-Devils (Original Serialized Version)",
    "Old version of Yitian Sword and Dragon Sword": "The Heaven Sword and Dragon Saber (Original Serialized Version)",
}

# Work-number-specific fixes (for titles shared by multiple works)
WORK_NUMBER_FIXES = {
    # D56: 神鵰俠侶 — the sequel, not 射鵰
    "D56": "The Return of the Condor Heroes",
    # D301: 舊版射鵰英雄傳
    "D301": "The Legend of the Condor Heroes (Original Serialized Version)",
    # D354: 舊版神鵰俠侶
    "D354": "The Return of the Condor Heroes (Original Serialized Version)",
}


def main():
    dry_run = "--dry-run" in sys.argv

    con = duckdb.connect(str(DB_PATH))
    updated = 0
    skipped = 0

    # Apply work-number-specific fixes first
    for work_number, new_title in sorted(WORK_NUMBER_FIXES.items()):
        row = con.execute(
            "SELECT work_id, title_english FROM works WHERE work_number = ?",
            [work_number]
        ).fetchone()
        if not row:
            print(f"  SKIP (not found): {work_number}")
            skipped += 1
            continue
        work_id, current_title = row
        if dry_run:
            print(f"  [DRY RUN] {work_number}: {current_title!r} -> {new_title!r}")
        else:
            con.execute("UPDATE works SET title_english = ? WHERE work_id = ?", [new_title, work_id])
            print(f"  UPDATED {work_number}: {current_title!r} -> {new_title!r}")
        updated += 1

    # Apply title-based fixes
    for current_title, new_title in sorted(TITLE_FIXES.items()):
        rows = con.execute(
            "SELECT work_id, work_number, title_english FROM works WHERE title_english = ?",
            [current_title]
        ).fetchall()

        if not rows:
            print(f"  SKIP (not found): {current_title}")
            skipped += 1
            continue

        for work_id, work_number, _ in rows:
            if dry_run:
                print(f"  [DRY RUN] {work_number}: {current_title!r} -> {new_title!r}")
            else:
                con.execute("UPDATE works SET title_english = ? WHERE work_id = ?", [new_title, work_id])
                print(f"  UPDATED {work_number}: {current_title!r} -> {new_title!r}")
            updated += 1

    con.close()

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Updated: {updated}, Skipped: {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
