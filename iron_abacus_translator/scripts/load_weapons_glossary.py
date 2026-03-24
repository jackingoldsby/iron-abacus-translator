#!/usr/bin/env python3
"""
Load Chinese Weapons Glossary into DuckDB

Converts chinese_weapons_glossary.json into the DuckDB glossary table
used by the translation pipeline (utils/glossary.py).

Usage:
    python scripts/load_weapons_glossary.py
    python scripts/load_weapons_glossary.py --db-path /path/to/glossary.duckdb
    python scripts/load_weapons_glossary.py --dry-run
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Weapons whose generic forms (刀/劍/槍/棍) appear very frequently in wuxia
_HIGH_FREQUENCY_IDS = {
    "dao_generic", "jian", "qiang", "gun", "bishou",
    "dadao", "duandao", "shuangjian", "shuangdao",
}

# Simplified → Traditional mapping for characters that appear in weapon names.
# The legendary weapons section of the glossary JSON uses simplified chinese.
_SIMP_TO_TRAD = str.maketrans({
    "龙": "龍", "剑": "劍", "铁": "鐵", "飞": "飛",
    "蛇": "蛇", "画": "畫", "青": "青", "血": "血",
    "碧": "碧", "玄": "玄", "金": "金", "狗": "狗",
    "李": "李", "小": "小", "刀": "刀", "棒": "棒",
    "偃": "偃", "月": "月", "关": "關", "马": "馬",
    "长": "長", "双": "雙", "节": "節", "锤": "錘",
})


def _to_traditional(text: str) -> str:
    """Convert simplified Chinese characters to traditional where known."""
    return text.translate(_SIMP_TO_TRAD)

# DuckDB table DDL — matches schema in scripts/deduplicate_glossary.py
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS glossary (
    id INTEGER PRIMARY KEY,
    chinese VARCHAR UNIQUE NOT NULL,
    pinyin VARCHAR NOT NULL,
    translation_strategy VARCHAR NOT NULL,
    recommended_form VARCHAR NOT NULL,
    footnote_template VARCHAR NOT NULL,
    category VARCHAR NOT NULL,
    rationale VARCHAR,
    deduplication_strategy VARCHAR NOT NULL,
    expected_frequency VARCHAR NOT NULL,
    source VARCHAR NOT NULL
)
"""


def build_footnote_template(weapon: dict) -> str:
    """
    Build a compact footnote from weapon entry fields.

    Focuses on what a reader needs: pinyin, translation, and the key
    taxonomic/cultural fact that makes this term worth footnoting.
    """
    pinyin = weapon["pinyin"]
    primary = weapon["correct_translations"][0]
    desc = weapon.get("description", "")
    wuxia = weapon.get("wuxia_connotation", "")

    footnote = f"{pinyin} — {primary}."

    # Add the first substantive sentence from description
    if desc:
        first_sentence = desc.split(". ")[0].rstrip(".")
        # Skip if it just restates the translation or is too short
        if len(first_sentence) > 20 and primary.lower() not in first_sentence.lower():
            footnote += f" {first_sentence}."
    # If no good description, try wuxia connotation
    elif wuxia:
        first_sentence = wuxia.split(". ")[0].rstrip(".")
        if len(first_sentence) > 20:
            footnote += f" {first_sentence}."

    return footnote


def build_glossary_rows(weapons_data: dict) -> list[dict]:
    """
    Convert weapons JSON into glossary table rows.

    Uses chinese_traditional since source texts are traditional Chinese.
    """
    rows = []
    weapons = weapons_data.get("weapons", [])

    for weapon in weapons:
        weapon_id = weapon.get("id", "")
        chinese = weapon.get("chinese_traditional", weapon.get("chinese_simplified", ""))
        if not chinese:
            logger.warning(f"Skipping weapon {weapon_id}: no Chinese characters")
            continue

        row = {
            "chinese": chinese,
            "pinyin": weapon.get("pinyin", ""),
            "translation_strategy": "ENGLISH_ONLY",
            "recommended_form": weapon["correct_translations"][0],
            "footnote_template": build_footnote_template(weapon),
            "category": "weapons",
            "rationale": weapon.get("translation_rule", ""),
            "deduplication_strategy": "FIRST_OCCURRENCE_ONLY",
            "expected_frequency": (
                "HIGH" if weapon_id in _HIGH_FREQUENCY_IDS else "MEDIUM"
            ),
            "source": "chinese_weapons_glossary",
        }
        rows.append(row)

        # Also load alternate names (e.g. 雁翎刀 for yanmaodao)
        for aka in weapon.get("also_known_as", []):
            # Format: "雁翎刀 yànlíngdāo (goose-feather sabre/goose-quill sabre)"
            parts = aka.strip().split(None, 1)
            if parts:
                aka_chinese = _to_traditional(parts[0])
                aka_pinyin = ""
                aka_desc = ""
                if len(parts) > 1:
                    rest = parts[1]
                    # Split pinyin from parenthetical
                    if "(" in rest:
                        aka_pinyin = rest[:rest.index("(")].strip()
                        aka_desc = rest[rest.index("(") + 1:].rstrip(")")
                    else:
                        aka_pinyin = rest.strip()

                aka_row = {
                    "chinese": aka_chinese,
                    "pinyin": aka_pinyin or weapon.get("pinyin", ""),
                    "translation_strategy": "ENGLISH_ONLY",
                    "recommended_form": (
                        aka_desc.split("/")[0].strip()
                        if aka_desc
                        else weapon["correct_translations"][0]
                    ),
                    "footnote_template": build_footnote_template(weapon),
                    "category": "weapons",
                    "rationale": weapon.get("translation_rule", ""),
                    "deduplication_strategy": "FIRST_OCCURRENCE_ONLY",
                    "expected_frequency": "MEDIUM",
                    "source": "chinese_weapons_glossary",
                }
                rows.append(aka_row)

    # Also load legendary weapons as proper-noun entries
    # NB: The JSON uses simplified Chinese for these — convert to traditional
    legendary = weapons_data.get("common_legendary_weapons_in_wuxia", {})
    for lw in legendary.get("weapons", []):
        chinese = _to_traditional(lw.get("chinese", ""))
        if not chinese:
            continue
        row = {
            "chinese": chinese,
            "pinyin": lw.get("pinyin", ""),
            "translation_strategy": "ENGLISH_ONLY",
            "recommended_form": lw["correct_translation"],
            "footnote_template": (
                f"{lw['pinyin']} — {lw['correct_translation']}. "
                f"From {lw.get('source', 'Chinese literary tradition')}."
            ),
            "category": "weapons",
            "rationale": (
                f"Legendary weapon. Common mistranslation: {lw.get('common_mistranslation', 'N/A')}"
            ),
            "deduplication_strategy": "FIRST_OCCURRENCE_ONLY",
            "expected_frequency": "LOW",
            "source": "chinese_weapons_glossary",
        }
        rows.append(row)

    # Load supplementary entries (terms not in the main weapons JSON)
    supplementary = weapons_data.get("supplementary_entries", [])
    for entry in supplementary:
        row = {
            "chinese": entry["chinese"],
            "pinyin": entry.get("pinyin", ""),
            "translation_strategy": entry.get("translation_strategy", "ENGLISH_ONLY"),
            "recommended_form": entry["recommended_form"],
            "footnote_template": entry.get("footnote_template", ""),
            "category": entry.get("category", "weapons"),
            "rationale": entry.get("rationale", ""),
            "deduplication_strategy": entry.get(
                "deduplication_strategy", "FIRST_OCCURRENCE_ONLY"
            ),
            "expected_frequency": entry.get("expected_frequency", "MEDIUM"),
            "source": entry.get("source", "chinese_weapons_glossary"),
        }
        rows.append(row)

    return rows


def load_into_duckdb(rows: list[dict], db_path: Path, dry_run: bool = False):
    """Insert/upsert rows into the DuckDB glossary table."""
    import duckdb

    if dry_run:
        logger.info(f"[DRY RUN] Would load {len(rows)} entries into {db_path}")
        for r in rows[:5]:
            logger.info(f"  {r['chinese']} → {r['recommended_form']}")
        if len(rows) > 5:
            logger.info(f"  ... and {len(rows) - 5} more")
        return

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))

    # Create table if not exists
    conn.execute(_CREATE_TABLE_SQL)

    # Get current max id
    result = conn.execute("SELECT COALESCE(MAX(id), 0) FROM glossary").fetchone()
    next_id = result[0] + 1

    inserted = 0
    skipped = 0
    for row in rows:
        # Check for existing entry (upsert by chinese)
        existing = conn.execute(
            "SELECT id FROM glossary WHERE chinese = ?", [row["chinese"]]
        ).fetchone()

        if existing:
            # Update existing entry
            conn.execute(
                """UPDATE glossary SET
                    pinyin = ?, translation_strategy = ?, recommended_form = ?,
                    footnote_template = ?, category = ?, rationale = ?,
                    deduplication_strategy = ?, expected_frequency = ?, source = ?
                WHERE chinese = ?""",
                [
                    row["pinyin"], row["translation_strategy"], row["recommended_form"],
                    row["footnote_template"], row["category"], row["rationale"],
                    row["deduplication_strategy"], row["expected_frequency"], row["source"],
                    row["chinese"],
                ],
            )
            skipped += 1
        else:
            conn.execute(
                """INSERT INTO glossary
                    (id, chinese, pinyin, translation_strategy, recommended_form,
                     footnote_template, category, rationale,
                     deduplication_strategy, expected_frequency, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    next_id,
                    row["chinese"], row["pinyin"], row["translation_strategy"],
                    row["recommended_form"], row["footnote_template"],
                    row["category"], row["rationale"],
                    row["deduplication_strategy"], row["expected_frequency"],
                    row["source"],
                ],
            )
            next_id += 1
            inserted += 1

    conn.close()
    logger.info(f"Loaded {inserted} new, updated {skipped} existing → {db_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Load Chinese weapons glossary into DuckDB"
    )
    parser.add_argument(
        "--glossary-json",
        type=Path,
        default=_PROJECT_ROOT / "chinese_weapons_glossary.json",
        help="Path to weapons glossary JSON",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Path to glossary.duckdb (default: from environment config)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be loaded without writing",
    )
    args = parser.parse_args()

    # Resolve DB path
    if args.db_path is None:
        from utils.environment_config import get_or_create_config
        args.db_path = get_or_create_config().glossary_path

    # Load JSON
    logger.info(f"Reading weapons glossary: {args.glossary_json}")
    with open(args.glossary_json, "r", encoding="utf-8") as f:
        weapons_data = json.load(f)

    weapon_count = len(weapons_data.get("weapons", []))
    legendary_count = len(
        weapons_data.get("common_legendary_weapons_in_wuxia", {}).get("weapons", [])
    )
    logger.info(f"Found {weapon_count} weapons + {legendary_count} legendary weapons")

    # Build rows
    rows = build_glossary_rows(weapons_data)
    logger.info(f"Built {len(rows)} glossary entries (including alternates)")

    # Check for duplicate chinese values within our rows
    seen = {}
    deduped = []
    for row in rows:
        if row["chinese"] in seen:
            logger.warning(
                f"Duplicate chinese '{row['chinese']}' — keeping first occurrence"
            )
        else:
            seen[row["chinese"]] = True
            deduped.append(row)
    rows = deduped

    # Load into DuckDB
    load_into_duckdb(rows, args.db_path, dry_run=args.dry_run)

    logger.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
