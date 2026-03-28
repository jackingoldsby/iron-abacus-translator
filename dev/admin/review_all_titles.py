#!/usr/bin/env python3
"""
Review all 640 English titles via DeepSeek (50 parallel workers).
Outputs a TSV of suggested changes for human review.

Usage:
    python dev/admin/review_all_titles.py
    python dev/admin/review_all_titles.py --output /tmp/title_review.tsv
"""

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent / "iron_abacus_translator"
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = Path.home() / "project_files" / "translation_project" / "db" / "works_translator.duckdb"
BATCH_SIZE = 30
WORKERS = 50


def load_all_works(con):
    rows = con.execute("""
        SELECT work_number, title_chinese, title_english, author_chinese, author_english
        FROM works ORDER BY work_number
    """).fetchall()
    cols = [d[0] for d in con.description]
    return [dict(zip(cols, r)) for r in rows]


def build_review_prompt(batch):
    lines = []
    for w in batch:
        lines.append(f"{w['work_number']}\t{w['title_chinese']}\t{w['title_english']}\t{w.get('author_chinese','')}")

    works_block = "\n".join(lines)

    return f"""As a sinologist and wuxia literary scholar, review these English translations of Chinese book titles.
For each work, evaluate the current English title and either APPROVE it or suggest a BETTER translation.

RULES:
- Use established/canonical English titles where they exist (e.g. from published translations)
- Translate ALL Chinese — no untranslated pinyin except proper nouns (character names, place names like Kunlun, Wudang)
- "Jianghu" may remain as-is (established loanword in wuxia)
- Titles should be literary and evocative, suitable for a published English translation
- Keep the original meaning — don't invent new meanings
- For series volumes, use consistent "Volume N" or "Part N" format
- 刀 = blade/saber (not knife), 劍 = sword, 簫 = flute, 琴 = zither, 槍 = spear

FORMAT: Return a JSON array. Each element:
{{"work_number": "...", "verdict": "APPROVE" or "CHANGE", "suggested": "new title or null", "reason": "brief reason if CHANGE"}}

Return ONLY the JSON array. No markdown fences.

WORKS (tab-separated: work_number, title_chinese, title_english_current, author_chinese):
{works_block}"""


def call_deepseek(prompt):
    from utils.clients.llm_config import get_llm_client
    from utils.clients.llm_client import LLMRequest

    client = get_llm_client(component="title_review", provider="deepseek", model="deepseek-chat")
    request = LLMRequest(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=8000,
    )
    response = client.chat(request)
    content = response.text

    if "```json" in content:
        content = content.split("```json", 1)[1].rsplit("```", 1)[0]
    elif "```" in content:
        content = content.split("```", 1)[1].rsplit("```", 1)[0]

    try:
        return json.loads(content.strip())
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse response: {e}")
        logger.debug(f"Content: {content[:500]}")
        return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="/tmp/title_review.tsv")
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args()

    # Load .env
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass

    con = duckdb.connect(str(DB_PATH), read_only=True)
    works = load_all_works(con)
    con.close()

    # Split into batches
    batches = []
    for i in range(0, len(works), args.batch_size):
        batches.append(works[i:i + args.batch_size])

    print(f"Reviewing {len(works)} titles in {len(batches)} batches with {args.workers} workers...\n")

    # Build work lookup for output
    work_map = {w["work_number"]: w for w in works}

    all_changes = []
    all_approvals = 0

    def fetch_batch(batch_idx_and_batch):
        batch_idx, batch = batch_idx_and_batch
        prompt = build_review_prompt(batch)
        try:
            results = call_deepseek(prompt)
            logger.info(f"Batch {batch_idx + 1}/{len(batches)}: {len(results)} results")
            return batch_idx, results
        except Exception as e:
            logger.error(f"Batch {batch_idx + 1} failed: {e}")
            return batch_idx, []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch_batch, (i, b)): i for i, b in enumerate(batches)}

        for future in as_completed(futures):
            batch_idx, results = future.result()
            for r in results:
                if r.get("verdict") == "CHANGE":
                    wn = r.get("work_number", "?")
                    w = work_map.get(wn, {})
                    all_changes.append({
                        "work_number": wn,
                        "title_chinese": w.get("title_chinese", ""),
                        "current": w.get("title_english", ""),
                        "suggested": r.get("suggested", ""),
                        "reason": r.get("reason", ""),
                    })
                else:
                    all_approvals += 1

    # Sort by work_number
    all_changes.sort(key=lambda x: x["work_number"])

    # Write TSV
    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("work_number\ttitle_chinese\tcurrent_english\tsuggested_english\treason\n")
        for c in all_changes:
            f.write(f"{c['work_number']}\t{c['title_chinese']}\t{c['current']}\t{c['suggested']}\t{c['reason']}\n")

    print(f"\n{'=' * 60}")
    print(f"  Review complete")
    print(f"  Approved:  {all_approvals}")
    print(f"  Changes:   {len(all_changes)}")
    print(f"  Output:    {output_path}")
    print(f"{'=' * 60}")

    # Print changes to stdout too
    if all_changes:
        print(f"\nSuggested changes:\n")
        for c in all_changes:
            print(f"  {c['work_number']}: {c['current']!r} -> {c['suggested']!r}")
            if c["reason"]:
                print(f"    reason: {c['reason']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
