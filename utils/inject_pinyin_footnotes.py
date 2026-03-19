#!/usr/bin/env python3
"""
Inject first-occurrence footnotes for italicized pinyin terms.

When the translator keeps a term in italicized pinyin (*qì*, *jiānghú*),
it signals the term was deliberately left untranslated.  The reader needs
a footnote on the first occurrence to understand what it means.

This utility:
  1. Scans all translated text for *pinyin* patterns
  2. Checks which ones already have a footnote somewhere in the work
  3. For those that don't, looks up the definition from:
     a. The suppress list (config/suppress_list.json)
     b. A built-in wuxia glossary (for terms not in the suppress list)
  4. Injects a footnote at the first occurrence, with proper marker placement

Run AFTER translation, BEFORE cleanup or EPUB generation.

Usage:
    python utils/inject_pinyin_footnotes.py --input translated.json --output injected.json
    python utils/inject_pinyin_footnotes.py --input translated.json --dry-run
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_SUPPRESS_LIST_PATH = Path(__file__).parent.parent / "config" / "suppress_list.json"

# Tone mark → base letter mapping
_TONE_MAP = str.maketrans(
    "āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ",
    "aaaaeeeeiiiioooouuuuüüüü",
)


def _strip_tones(s: str) -> str:
    return s.translate(_TONE_MAP)


# Built-in glossary for common wuxia terms NOT in the suppress list.
# Format: tone-stripped pinyin → (chinese, toned pinyin, english explanation)
_BUILTIN_GLOSSARY: Dict[str, Tuple[str, str, str]] = {
    # --- Terms missing from suppress list ---
    "ge": ("哥", "gē", "Elder brother — a respectful address for an older male, "
           "not necessarily a blood relative"),
    "gonggong": ("公公", "gōnggōng", "A respectful address for a eunuch or "
                 "an elderly man; in the imperial court, specifically a palace eunuch"),
    "huohou": ("火候", "huǒhòu", "Lit. 'fire timing' — the level of attainment "
               "in one's martial arts or internal cultivation, analogous to a craftsman's "
               "mastery of heat control in forging or alchemy"),
    "jianlu": ("劍路", "jiànlù", "Sword path — the characteristic sequence and "
               "trajectory of movements in a sword style or technique"),
    "meizi": ("妹子", "mèizi", "Younger sister — an informal, affectionate address "
              "for a younger woman"),
    "shige": ("師哥", "shīgē", "Senior martial brother — informal variant of "
              "*shīxiōng*, using the familiar 哥 (elder brother) instead of the "
              "formal 兄"),
    "sishu": ("四書", "sìshū", "The Four Books — the foundational Confucian texts: "
              "Great Learning, Doctrine of the Mean, Analects, and Mencius; "
              "the core curriculum for the imperial civil service examinations"),
    "xinfa": ("心法", "xīnfǎ", "Heart method — the mental cultivation techniques "
              "and meditative principles underlying a martial art or internal energy "
              "practice; the 'inner teaching' as distinct from physical forms"),
    "zhuangzhu": ("莊主", "zhuāngzhǔ", "Manor lord — the master of a *zhuāng* "
                  "(fortified manor estate), a common power base in the *jiānghú*"),
    # --- Martial arts terms ---
    "bianfa": ("鞭法", "biānfǎ", "Whip techniques — the system of flexible-weapon "
               "combat using chain whips or segmented steel whips"),
    "daofa": ("刀法", "dāofǎ", "Sabre techniques — the system of single-edged blade "
              "combat, favoring power and decisive strikes over elegance"),
    "quanfa": ("拳法", "quánfǎ", "Fist techniques — the system of unarmed combat "
               "forms and striking methods"),
    "shenfa": ("身法", "shēnfǎ", "Body method — the comprehensive system of footwork, "
               "posture, dodging, and positioning that defines a martial artist's movement"),
    "zhangfa": ("掌法", "zhǎngfǎ", "Palm techniques — open-hand combat methods, "
                "often associated with internal martial arts styles"),
    "zhangfeng": ("掌風", "zhǎngfēng", "Palm wind — the blast of air pressure generated "
                  "by a powerful palm strike, capable of injuring at short range without "
                  "physical contact"),
    "zhangli": ("掌力", "zhǎnglì", "Palm force — the focused internal energy "
                "channeled through an open-palm strike"),
    "qinna": ("擒拿", "qínná", "Seize-and-lock techniques — grappling methods "
              "targeting joints, pressure points, and tendons to subdue an opponent"),
    "shaqi": ("殺氣", "shāqì", "Killing intent — a palpable aura of murderous "
              "determination that skilled martial artists can project and sense"),
    "huajin": ("化勁", "huàjìn", "Neutralizing force — the advanced internal arts "
               "skill of redirecting or dissolving an opponent's incoming power"),
    "chaizhao": ("拆招", "chāizhāo", "Exchanging moves — the back-and-forth sequence "
                 "of attack and counter-attack between martial artists"),
    # --- Honorifics and relationships ---
    "shixiong": ("師兄", "shīxiōng", "Senior martial brother — a fellow disciple "
                 "who entered the school or master's tutelage earlier"),
    "shimei": ("師妹", "shīmèi", "Junior martial sister — a female fellow disciple "
               "who entered the school later"),
    "shidi": ("師弟", "shīdì", "Junior martial brother — a fellow disciple who "
              "entered the school later"),
    "shishu": ("師叔", "shīshū", "Martial uncle — one's master's junior martial "
               "brother; a generation above but junior within that generation"),
    "shizu": ("師祖", "shīzǔ", "Martial grandmaster — one's master's master; "
              "the founding or senior generation figure of a lineage"),
    "shizhi": ("師侄", "shīzhí", "Martial nephew — the disciple of one's own "
               "martial brother or sister; one generation below"),
    "enshi": ("恩師", "ēnshī", "Benefactor-master — a master to whom one owes "
              "a particularly deep debt of gratitude, often for life-saving "
              "instruction or patronage"),
    # Note: 世兄 (shìxiōng) shares the same tone-stripped key as 師兄 (shīxiōng).
    # 師兄 takes priority as it's far more common.
    "xiong": ("兄", "xiōng", "Elder brother — a formal, respectful address for a man "
              "of similar or higher standing, often used between martial peers"),
    "mei": ("妹", "mèi", "Younger sister — a term of endearment or respectful "
            "address for a younger woman, especially in martial arts circles"),
    "di": ("弟", "dì", "Younger brother — a formal address for a junior male, "
           "often used between martial peers"),
    "ye": ("爺", "yé", "Lord / grandfather — a respectful address for an older man "
           "of authority or high status"),
    "dage": ("大哥", "dàgē", "Eldest brother — the most senior among sworn brothers "
             "or the leader of a group of peers"),
    "biaotou": ("鏢頭", "biāotóu", "Escort chief — the leader of an armed escort "
                "company (*biāojú*) that protected merchant caravans and valuable "
                "shipments across dangerous territory"),
    "zhanglao": ("長老", "zhǎnglǎo", "Elder — a senior-ranking member of a martial "
                 "arts sect, typically serving as instructor, advisor, or enforcer "
                 "of sect discipline"),
    # --- Cultural terms ---
    "caomang": ("草莽", "cǎomǎng", "The greenwood — the world of outlaws and "
                "wandering fighters outside both official society and the established "
                "martial sects; rougher and less refined than the *jiānghú* proper"),
    "choujia": ("仇家", "chóujiā", "Mortal enemy — a person or clan against whom "
                "one holds a blood feud or deep grudge; revenge obligations in the "
                "*jiānghú* could span generations"),
    "haoke": ("豪客", "háokè", "Gallant wanderer — a bold, generous traveler of the "
              "*jiānghú*, typically one with both martial skill and lavish generosity"),
    "enyuan": ("恩怨", "ēnyuàn", "Debts of gratitude and grudges — the complex web "
               "of mutual obligations and vendettas that governs relationships in the "
               "*jiānghú*; a central moral framework of wuxia fiction"),
    # --- Sect/organization terms ---
    "zongmen": ("宗門", "zōngmén", "Sect — a formal martial arts school or religious "
                "order with an established hierarchy, lineage, and body of techniques"),
    "tianlong": ("天龍", "tiānlóng", "Celestial Dragon — lit. 'heavenly dragon'; "
                 "here the name of the Tiānlóng Mén (Celestial Dragon Sect)"),
    "xuedao": ("穴道", "xuédào", "Acupoints — specific points on the body's meridian "
               "network that can be struck or pressed to paralyze, heal, or kill"),
}


def _load_suppress_glossary(
    suppress_path: Optional[Path] = None,
) -> Dict[str, Tuple[str, str, str]]:
    """Load suppress list as a glossary keyed by tone-stripped pinyin.

    Returns dict of stripped_pinyin → (chinese, toned_pinyin, english).
    """
    path = suppress_path or _SUPPRESS_LIST_PATH
    glossary: Dict[str, Tuple[str, str, str]] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            items = json.load(f)
        for item in items:
            pinyin = item.get("pinyin", "").strip()
            if pinyin:
                key = _strip_tones(pinyin.lower())
                glossary[key] = (
                    item.get("chinese", ""),
                    pinyin,
                    item.get("english", ""),
                )
    except Exception as e:
        logger.warning(f"Could not load suppress list from {path}: {e}")
    return glossary


def _find_italicized_pinyins(data: Dict[str, Any]) -> Set[str]:
    """Find all unique italicized pinyin terms in translated text."""
    italic_re = re.compile(r"\*([a-zA-Zàáèéìíòóùúǎǐǒǔāēīōūüǖǘǚǜ]+)\*")
    pinyins: Set[str] = set()
    for chapter in data.get("structure", {}).get("body", {}).get("chapters", []):
        for block in chapter.get("content_blocks", []):
            text = block.get("translated_content", "")
            if text:
                for m in italic_re.finditer(text):
                    pinyins.add(m.group(1).lower())
    return pinyins


def _find_footnoted_pinyins(data: Dict[str, Any]) -> Set[str]:
    """Find all pinyin values that already have a footnote somewhere."""
    pinyins: Set[str] = set()
    for chapter in data.get("structure", {}).get("body", {}).get("chapters", []):
        for block in chapter.get("content_blocks", []):
            for fn in block.get("footnotes", []):
                p = fn.get("pinyin", "").strip().lower()
                if p:
                    for w in p.split():
                        pinyins.add(w)
                        pinyins.add(_strip_tones(w))
    return pinyins


def inject_pinyin_footnotes(
    data: Dict[str, Any],
    suppress_path: Optional[Path] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Inject first-occurrence footnotes for unfootnoted italicized pinyin terms.

    Args:
        data: Translated JSON data (modified in place unless dry_run)
        suppress_path: Path to suppress list JSON
        dry_run: If True, report what would be injected but don't modify data

    Returns:
        Dict with injection stats: {injected: [...], skipped_no_def: [...]}
    """
    # Step 1: Find all italicized pinyin terms
    italic_pinyins = _find_italicized_pinyins(data)
    if not italic_pinyins:
        logger.info("No italicized pinyin terms found")
        return {"injected": [], "skipped_no_def": []}

    logger.info(f"Found {len(italic_pinyins)} unique italicized pinyin terms")

    # Step 2: Find which already have footnotes
    footnoted = _find_footnoted_pinyins(data)

    # Step 3: Identify terms needing injection
    needs_footnote = set()
    for p in italic_pinyins:
        if p not in footnoted and _strip_tones(p) not in footnoted:
            needs_footnote.add(p)

    if not needs_footnote:
        logger.info("All italicized terms already have footnotes")
        return {"injected": [], "skipped_no_def": []}

    logger.info(f"{len(needs_footnote)} terms need first-occurrence footnotes")

    # Step 4: Look up definitions
    suppress_glossary = _load_suppress_glossary(suppress_path)
    # Merge: builtin takes lower priority
    glossary = dict(_BUILTIN_GLOSSARY)
    glossary.update(suppress_glossary)

    injected = []
    skipped = []

    for pinyin in sorted(needs_footnote):
        stripped = _strip_tones(pinyin)
        entry = glossary.get(stripped)
        if entry:
            injected.append({
                "pinyin_italic": pinyin,
                "chinese": entry[0],
                "pinyin_toned": entry[1],
                "english": entry[2],
            })
        else:
            skipped.append(pinyin)

    if skipped:
        logger.warning(
            f"No definition found for {len(skipped)} terms: {skipped}"
        )

    logger.info(f"Will inject {len(injected)} first-occurrence footnotes")

    if dry_run:
        return {"injected": injected, "skipped_no_def": skipped}

    # Step 5: Inject footnotes at first occurrence
    # Build a set of pinyins already injected (to ensure first-occurrence only)
    injected_pinyins: Set[str] = set()

    # Build lookup: stripped pinyin → injection entry
    inject_lookup: Dict[str, Dict] = {}
    for entry in injected:
        key = _strip_tones(entry["pinyin_italic"])
        inject_lookup[key] = entry

    italic_re = re.compile(r"\*([a-zA-Zàáèéìíòóùúǎǐǒǔāēīōūüǖǘǚǜ]+)\*")

    for chapter in data.get("structure", {}).get("body", {}).get("chapters", []):
        for block in chapter.get("content_blocks", []):
            text = block.get("translated_content", "")
            if not text:
                continue

            footnotes = block.get("footnotes", [])
            new_footnotes = []

            # Collect insertions first (position, marker) then apply in reverse
            insertions: List[Tuple[int, str]] = []

            for m in italic_re.finditer(text):
                term = m.group(1).lower()
                stripped = _strip_tones(term)

                if stripped in injected_pinyins:
                    continue  # Already injected in an earlier block
                if stripped not in inject_lookup:
                    continue  # No definition available

                entry = inject_lookup[stripped]
                injected_pinyins.add(stripped)

                # Create footnote
                next_key = len(footnotes) + len(new_footnotes) + 1
                new_footnotes.append({
                    "key": next_key,
                    "ideogram": entry["chinese"],
                    "pinyin": entry["pinyin_toned"],
                    "explanation": entry["english"],
                })

                # Queue marker insertion after the closing *
                insertions.append((m.end(), f"[{next_key}]"))

            # Apply insertions in reverse order so positions stay valid
            for pos, marker in reversed(insertions):
                text = text[:pos] + marker + text[pos:]

            if new_footnotes:
                block["translated_content"] = text
                block["footnotes"] = footnotes + new_footnotes

    return {"injected": injected, "skipped_no_def": skipped}


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Inject first-occurrence footnotes for italicized pinyin terms"
    )
    parser.add_argument("--input", required=True, help="Input translated JSON")
    parser.add_argument("--output", help="Output JSON (default: overwrite input)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be injected without modifying")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(levelname)s - %(message)s")

    input_path = Path(args.input)
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = inject_pinyin_footnotes(data, dry_run=args.dry_run)

    print(f"\nInjected: {len(result['injected'])}")
    for entry in result["injected"]:
        print(f"  *{entry['pinyin_italic']}* → {entry['chinese']} — {entry['english'][:60]}")

    if result["skipped_no_def"]:
        print(f"\nSkipped (no definition): {result['skipped_no_def']}")

    if not args.dry_run and result["injected"]:
        out = Path(args.output) if args.output else input_path
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\nWrote: {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
