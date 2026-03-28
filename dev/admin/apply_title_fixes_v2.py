#!/usr/bin/env python3
"""
Apply curated title_english fixes — round 2.
Fixes untranslated pinyin, mangled translations, and wrong established titles.

Usage:
    python dev/admin/apply_title_fixes_v2.py --dry-run
    python dev/admin/apply_title_fixes_v2.py
"""

import duckdb
import sys
from pathlib import Path

DB_PATH = Path.home() / "project_files" / "translation_project" / "db" / "works_translator.duckdb"

# Work-number-specific fixes (safest — no ambiguity)
WORK_NUMBER_FIXES = {
    # Untranslated pinyin
    "D10S5": "Iron Sword, Crimson Trace",
    "D1104": "Ink Feather, Azure Steed",
    "D1123": "The Proud Lord's Blade",
    "D1150": "Jianghu: Ten Years of Night Rain and Lantern Light",
    "D1185": "Snow Spirit, Plum Soul",
    "D1186": "Eagle Soaring in the Sword Sea",
    "D1224": "Blade and Arrow, Tide of Love",
    "D1295": "Golden Armor, Cold Autumn Waters",
    "D1299": "Mandarin Ducks in a Troubled World",
    "D1309": "The Free Phoenix Lures the Mate",
    "D1345": "Shadow of a Knight, Crimson Beauty",
    "D1369": "Purple Mansion Mystery: The Thunder Sword",
    "D1411": "Sword Courage, Zither Heart",
    "D13I7": "Record of a Loyal Heart",
    "D13I8": "The Strange Knight of Jianghu",
    "D13J2": "Man of the Jianghu",
    "D13M9": "Sandalwood Chariot, Knight's Shadow",
    "D11N2": "The Dragon-Prancing Hero",
    "D12D6": "Cold Sword, Flying Oriole",
    "D12D9": "Record of Rivalries on the Imperial Frontier",
    "D12I0": "Road to the Ends of the Jianghu",
    "D12J6": "Nimble Swallow, Mighty Eagle",
    "D12M8": "Storm over the Tyrant Sea",
    "D14BA4": "The Hidden Sword of Xianzhou",
    "D14BC6": "Tiger-Herding in Three Mountains",
    "D14C0": "Record of the Sword's Courage and the Zither's Soul",
    "D14G8": "The Road of the Jianghu",
    "D14J4": "Moon Over the Mountain Pass",
    "D14X2": "Record of the Generals at He Yue",
    "I10A8": "The Golden Tripod and the Wandering Dragon",
    "I10K9": "Azure Skies and Red Dust",
    "I09D6": "Sword of the Xiang Consort",
    "D10P7": "Flicking the Sword in the Jianghu",

    # Mangled / nonsense translations
    "D1129": "Record of Chasing Clouds and Seizing Lightning",
    "D1243": "Heroes Contending in the Wilderness",
    "D1283": "Releasing the Crane to Capture the Dragon",
    "D12J7": "Where Tigers Crouch and Dragons Coil",
    "D12N7": "Blood Blade and Wine on the Jianghu Road",
    "D13M8": "Dragon-Tiger Combat",
    "D14B9": "Rouge and Swords",
    "D1160": "The Rouge Blade King",
    "D10T0": "Swords and Halberds of Lords",
    "D10T1": "Heavenly Sword and Peerless Blade",
    "D1509": "The Sun-Shooting Divine Sword",
    "D11D1": "Beauty Like Jade, Sword Like Rainbow",
    "D13K2": "Unending Grudges, Unending Love",
    "D11F5": "Holy Sword, Flying Frost",

    # Wrong established titles
    "D10U8A": "The Return of the Condor Heroes (Revised Edition)",
    "D10U8B": "The Return of the Condor Heroes (Revised Edition)",
    "D10U8C": "The Return of the Condor Heroes (Revised Edition)",
    "D10U8D": "The Return of the Condor Heroes (Revised Edition)",
    "D10P5": "White Horse Neighs in the Western Wind (Original Serialized Version)",
    "D191": "The Twin Dragons of the Great Tang",
    "D69": "A Step into the Past",
    "D81": "A Step into the Past (Revised Edition)",
    "D61": "The Young Flying Fox",
    "I0990": "Zhu Xian",
}


def main():
    dry_run = "--dry-run" in sys.argv

    con = duckdb.connect(str(DB_PATH))
    updated = 0
    skipped = 0

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
        if current_title == new_title:
            continue
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
