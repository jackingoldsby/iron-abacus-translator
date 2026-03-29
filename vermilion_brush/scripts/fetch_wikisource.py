#!/usr/bin/env python3
"""Fetch 三俠五義 from zh.wikisource.org and emit Jade Shuttle-compatible JSON.

Wikisource has all 120 chapters as clean digital text — no OCR needed.

Usage:
    python scripts/fetch_wikisource.py --output /path/to/raw_三俠五義.json
    python scripts/fetch_wikisource.py --output /path/to/raw.json --dry-run
    python scripts/fetch_wikisource.py --output /path/to/raw.json --log /path/to/fetch.log
"""

import argparse
import json
import logging
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

WIKISOURCE_API = "https://zh.wikisource.org/w/api.php"
WORK_TITLE = "三俠五義"
TOTAL_CHAPTERS = 120


def setup_logging(log_path: Path | None) -> logging.Logger:
    logger = logging.getLogger("wikisource_fetch")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_path), encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


def fetch_wikitext(page_title: str) -> str:
    """Fetch wikitext source of a Wikisource page via the MediaWiki API."""
    params = urllib.parse.urlencode({
        "action": "parse",
        "page": page_title,
        "prop": "wikitext",
        "format": "json",
    })
    url = f"{WIKISOURCE_API}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "VermilionBrush/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("parse", {}).get("wikitext", {}).get("*", "")


def parse_chapter_wikitext(wikitext: str) -> tuple[str, list[dict]]:
    """Parse chapter wikitext into a title and list of content blocks.

    Returns:
        (chapter_title, [{"tag": "p"|"verse", "content": "..."}])
    """
    lines = wikitext.split("\n")
    blocks = []
    title = ""

    # Extract title from == heading ==
    for line in lines:
        m = re.match(r"==\s*(.+?)\s*==", line)
        if m:
            title = m.group(1).strip()
            break

    # Skip header templates, extract body
    in_body = False
    current_para = []
    in_verse = False

    for line in lines:
        stripped = line.strip()

        # Skip template lines
        if stripped.startswith("{{") or stripped.startswith("}}"):
            continue
        if stripped.startswith("==") and stripped.endswith("=="):
            in_body = True
            continue
        if not in_body:
            continue

        # Verse lines (indented with ::; or :: in wikitext)
        if stripped.startswith("::"):
            if current_para:
                blocks.append({"tag": "p", "content": "".join(current_para)})
                current_para = []
            # Clean verse markup
            verse_text = re.sub(r"^::;?\s*", "", stripped)
            if verse_text:
                blocks.append({"tag": "verse", "content": verse_text})
            continue

        # Blank line = paragraph break
        if not stripped:
            if current_para:
                blocks.append({"tag": "p", "content": "".join(current_para)})
                current_para = []
            continue

        # Regular text — accumulate into paragraph
        current_para.append(stripped)

    # Flush remaining
    if current_para:
        blocks.append({"tag": "p", "content": "".join(current_para)})

    return title, blocks


def main():
    parser = argparse.ArgumentParser(description="Fetch 三俠五義 from Wikisource")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--log", help="Log file path")
    parser.add_argument("--dry-run", action="store_true", help="Show plan only")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between requests (be polite)")
    args = parser.parse_args()

    output_path = Path(args.output)
    log_path = Path(args.log) if args.log else output_path.with_suffix(".log")
    logger = setup_logging(log_path)

    logger.info("=" * 60)
    logger.info(f"Fetching {WORK_TITLE} from zh.wikisource.org")
    logger.info(f"Chapters: {TOTAL_CHAPTERS}")
    logger.info(f"Output: {output_path}")
    logger.info("=" * 60)

    if args.dry_run:
        for i in range(1, TOTAL_CHAPTERS + 1):
            page = f"{WORK_TITLE}/第{i:03d}回"
            logger.info(f"  Would fetch: {page}")
        logger.info("DRY RUN — done")
        return

    chapters = []
    toc = []
    total_chars = 0

    for i in range(1, TOTAL_CHAPTERS + 1):
        page_title = f"{WORK_TITLE}/第{i:03d}回"

        try:
            t0 = time.time()
            wikitext = fetch_wikitext(page_title)
            title, blocks = parse_chapter_wikitext(wikitext)

            if not title:
                title = f"第{i}回"

            char_count = sum(len(b["content"]) for b in blocks)
            total_chars += char_count

            chapter_idx = len(chapters)
            chapters.append({"title": title, "content": blocks})
            toc.append({"full_title": title, "chapter_ref": f"chapter_{chapter_idx}"})

            elapsed = time.time() - t0
            logger.info(
                f"[{i:3d}/{TOTAL_CHAPTERS}] {title[:30]:30s} | "
                f"{len(blocks):3d} blocks | {char_count:5d} chars | {elapsed:.1f}s"
            )

            time.sleep(args.delay)

        except Exception as e:
            logger.error(f"[{i:3d}/{TOTAL_CHAPTERS}] FAILED {page_title}: {e}")
            # Add empty chapter placeholder
            chapters.append({"title": f"第{i}回 [FETCH ERROR]", "content": []})
            toc.append({"full_title": f"第{i}回", "chapter_ref": f"chapter_{len(chapters) - 1}"})

    # Assemble Jade Shuttle JSON
    result = {
        "metadata": {
            "title": "三俠五義",
            "creator": "石玉昆",
            "language": "zh-Hant",
            "source": "zh.wikisource.org",
            "publisher": None,
        },
        "source": "zh.wikisource.org/wiki/三俠五義",
        "number_of_characters": total_chars,
        "toc": toc,
        "chapters": chapters,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info("=" * 60)
    logger.info(f"DONE: {len(chapters)} chapters, {total_chars} characters")
    logger.info(f"Output: {output_path}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
