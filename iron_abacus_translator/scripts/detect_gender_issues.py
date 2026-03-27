#!/usr/bin/env python3
"""
Detect potential gender pronoun issues in translated wuxia content.

Scans translated blocks in sliding windows and flags blocks where gender
pronouns (he/she/his/her) may be incorrect based on surrounding context.
Detection only — no modifications are made.

Usage:
    python scripts/detect_gender_issues.py D60 --chapter 1
    python scripts/detect_gender_issues.py D60
    python scripts/detect_gender_issues.py D60 --chapter 1 --dry-run
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from utils.clients import llm_chat_json
from utils.clients.llm_config import get_llm_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

TRANSLATED_DIR = Path("/Users/jacki/project_files/translation_project/translated")

# Force OpenAI gpt-4.1-nano regardless of global LLM_PROVIDER
_nano_client = get_llm_client(provider="openai", model="gpt-4.1-nano")

WINDOW_SIZE = 10
OVERLAP = 3
STEP = WINDOW_SIZE - OVERLAP  # 7

SYSTEM_PROMPT = """\
You are a proofreading assistant checking for gender errors in translated Chinese wuxia fiction.

Analyze the content blocks below. Flag ONLY blocks that contain a CLEAR gender error — where \
the text uses a gendered word that contradicts what the surrounding blocks establish about \
that character.

Error types to catch:
1. Wrong pronoun: he/him/his for a female character, or she/her/hers for a male character.
2. Wrong gendered noun: "two men" when one is female, "swordsman" for a woman, etc. \
Names containing 娘/姑/嫂/婆/妹/姐 indicate female characters.
3. Wrong gendered title: "Master" for a woman, "Mistress" for a man, etc.

CRITICAL RULES:
- ONLY report actual errors. If the gender usage is correct, do NOT include it.
- text_used and likely_correct MUST be different. If they would be the same, there is no error.
- Do NOT flag gender-ambiguous situations or cases where you are uncertain.
- Do NOT flag correct usage just because you analyzed it.
- Return {"issues": []} if no errors are found. An empty list is the expected common case.

Return JSON. Keep text_used SHORT — just the offending phrase, not the whole sentence:
{
  "issues": [
    {
      "block_id": "block_0067",
      "text_used": "these two men",
      "likely_correct": "the two of them",
      "character": "Zhèng Sānniáng",
      "reason": "Block 0066 establishes Zhèng Sānniáng is female (niáng = lady), so 'two men' is wrong"
    }
  ]
}"""


def find_translated_json(work_id: str) -> Path:
    """Find the translated JSON for a work ID."""
    work_dir = TRANSLATED_DIR / work_id
    if not work_dir.exists():
        raise FileNotFoundError(f"No translated directory for {work_id}")
    jsons = list(work_dir.glob("translated_*.json"))
    if not jsons:
        raise FileNotFoundError(f"No translated JSON in {work_dir}")
    if len(jsons) > 1:
        logger.warning(f"Multiple JSONs found, using first: {jsons[0].name}")
    return jsons[0]


def get_chapters(data):
    """Return the list of chapters from the translated JSON."""
    return data["structure"]["body"]["chapters"]


def build_window_text(blocks, start, end, max_chars_per_block=600):
    """Format blocks[start:end] as numbered text for the LLM prompt."""
    lines = []
    for block in blocks[start:end]:
        block_id = block.get("id", "unknown")
        text = block.get("translated_content") or block.get("content", "")
        if text.strip():
            # Truncate very long blocks to keep prompt focused
            if len(text) > max_chars_per_block:
                text = text[:max_chars_per_block] + "..."
            lines.append(f"[{block_id}]\n{text}")
    return "\n\n".join(lines)


def generate_windows(num_blocks):
    """Yield (start, end) tuples for sliding windows."""
    start = 0
    while start < num_blocks:
        end = min(start + WINDOW_SIZE, num_blocks)
        yield start, end
        if end >= num_blocks:
            break
        start += STEP


def scan_chapter(chapter_idx, chapter, dry_run=False):
    """Scan a single chapter for gender issues. Returns list of issues."""
    blocks = chapter.get("content_blocks", [])
    title = chapter.get("title", f"Chapter {chapter_idx + 1}")
    num_blocks = len(blocks)

    if num_blocks == 0:
        logger.info(f"  Chapter {chapter_idx + 1} ({title}): no blocks, skipping")
        return []

    windows = list(generate_windows(num_blocks))
    logger.info(
        f"  Chapter {chapter_idx + 1} ({title}): "
        f"{num_blocks} blocks, {len(windows)} windows"
    )

    if dry_run:
        for start, end in windows:
            block_ids = [
                blocks[i].get("id", f"block_{i}") for i in range(start, end)
            ]
            logger.info(f"    Window [{start}:{end}] → {block_ids[0]}..{block_ids[-1]}")
        return []

    all_issues = []
    seen_block_ids = set()

    for win_idx, (start, end) in enumerate(windows):
        window_text = build_window_text(blocks, start, end)
        if not window_text.strip():
            continue

        logger.info(f"    Window {win_idx + 1}/{len(windows)} [{start}:{end}]")

        try:
            result = llm_chat_json(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": window_text},
                ],
                client=_nano_client,
                model="gpt-4.1-nano",
                temperature=0.2,
                json_mode=True,
                max_tokens=800,
            )
        except Exception as e:
            logger.error(f"    LLM error on window [{start}:{end}]: {e}")
            continue

        issues = result.get("issues", [])
        for issue in issues:
            bid = issue.get("block_id", "")
            if bid not in seen_block_ids:
                seen_block_ids.add(bid)
                all_issues.append(issue)
                logger.info(
                    f"    ⚠ {bid}: \"{issue.get('text_used')}\" → "
                    f"\"{issue.get('likely_correct')}\" "
                    f"({issue.get('character', '?')})"
                )

        time.sleep(0.2)

    return all_issues


def detect_gender_issues(work_id: str, chapter_num=None, dry_run=False):
    """Main entry point: scan work for gender pronoun issues."""
    json_path = find_translated_json(work_id)
    logger.info(f"Loading {json_path.name}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    chapters = get_chapters(data)
    logger.info(f"Work {work_id}: {len(chapters)} chapters")

    if chapter_num is not None:
        if chapter_num < 1 or chapter_num > len(chapters):
            raise ValueError(
                f"Chapter {chapter_num} out of range (1-{len(chapters)})"
            )
        indices = [chapter_num - 1]
    else:
        indices = list(range(len(chapters)))

    all_issues = {}

    for ch_idx in indices:
        chapter = chapters[ch_idx]
        issues = scan_chapter(ch_idx, chapter, dry_run=dry_run)
        if issues:
            all_issues[f"chapter_{ch_idx + 1}"] = issues

    # Summary
    total = sum(len(v) for v in all_issues.values())
    logger.info(f"\n{'=' * 60}")
    if dry_run:
        logger.info(f"Dry run complete — no LLM calls made")
    elif total == 0:
        logger.info("No gender pronoun issues detected.")
    else:
        logger.info(f"Found {total} potential gender issue(s):")
        for ch_key, issues in all_issues.items():
            logger.info(f"\n  {ch_key}:")
            for issue in issues:
                logger.info(
                    f"    {issue['block_id']}: "
                    f"\"{issue.get('text_used', '?')}\" → "
                    f"\"{issue.get('likely_correct', '?')}\" "
                    f"— {issue.get('character', '?')}"
                )
                logger.info(f"      Reason: {issue.get('reason', 'N/A')}")

    return all_issues


def main():
    parser = argparse.ArgumentParser(
        description="Detect gender pronoun issues in translated wuxia content"
    )
    parser.add_argument("work_id", help="Work ID (e.g. D60)")
    parser.add_argument(
        "--chapter", type=int, default=None,
        help="Scan specific chapter number (1-based)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show windows without calling LLM"
    )
    args = parser.parse_args()
    detect_gender_issues(args.work_id, chapter_num=args.chapter, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
