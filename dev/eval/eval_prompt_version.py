#!/usr/bin/env python3
"""
Evaluate translation prompt quality by translating 16 sample blocks
(8 from each of 2 books) and measuring footnote metrics.
"""

import sys
import json
import re
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "iron_abacus_translator"))

import dotenv
dotenv.load_dotenv()

from processors.translator import TranslationService, TranslationRequest

from utils.environment_config import get_or_create_config
BASE = get_or_create_config().source_dir
BOOKS = [
    BASE / "work_0120/cleaned_D13G9_大唐游俠傳_梁羽生.json",
    BASE / "work_0123/cleaned_I09B3_武林天驕_梁羽生.json",
]

# Terms that should NEVER be footnoted
TRIVIAL_TERMS = {
    "鄉人", "villagers", "喟然微歎", "sigh", "蒼苔", "moss",
    "荒山僻徑", "mountain path", "少婦", "young woman", "裙布", "skirt",
    "山路", "path", "果品", "fruit", "甘淡泊", "content",
    "firewood", "wine", "tea", "chair", "table", "gate", "door",
    "ancient", "desolate", "remote", "barren", "elegant", "beautiful",
    "wept", "laughed", "feared", "worried", "pondered",
}


def evaluate():
    service = TranslationService(
        model="gpt-4.1-nano",
        temperature=0.3,
        max_retries=1,
        timeout=120,
    )

    total_fn = 0
    total_blocks = 0
    over_footnoted = 0  # >3 FN per block
    fn_in_fn = 0        # [N] inside footnote text
    trivial_count = 0
    clean_blocks = 0    # 0-1 footnotes
    trivial_examples = []

    for book_path in BOOKS:
        with open(book_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        if not chapters:
            print(f"No chapters in {book_path.name}")
            continue

        ch1 = chapters[0]
        blocks = ch1.get("content_blocks", [])[:8]
        book_name = book_path.stem.split("_")[1]

        print(f"\n{'='*50}")
        print(f"Book: {book_name} — {len(blocks)} blocks")
        print(f"{'='*50}")

        for i, block in enumerate(blocks):
            content = block.get("content", "")
            if not content or not content.strip():
                continue

            req = TranslationRequest(
                content_text_id=i + 1,
                content_source_text=content,
            )

            try:
                resp = service.translate(req)
                tac = resp.translated_annotated_content
                text = tac.annotated_content_text
                fns = tac.content_footnotes
                n_fn = len(fns)

                total_blocks += 1
                total_fn += n_fn

                if n_fn <= 1:
                    clean_blocks += 1
                if n_fn > 3:
                    over_footnoted += 1

                # Check FN-in-FN
                for fn in fns:
                    expl = fn.footnote_details.footnote_explanation
                    if re.search(r'\[\d+\]', expl):
                        fn_in_fn += 1
                        print(f"  !! FN-IN-FN: {expl[:80]}")

                # Check trivial
                for fn in fns:
                    ideogram = fn.footnote_details.footnote_ideogram
                    expl = fn.footnote_details.footnote_explanation.lower()
                    for term in TRIVIAL_TERMS:
                        if term in ideogram or term in expl:
                            trivial_count += 1
                            trivial_examples.append(f"{ideogram}: {expl[:60]}")
                            break

                status = "OK" if n_fn <= 2 else "HIGH" if n_fn <= 3 else "OVER"
                print(f"  Block {i}: {n_fn} FN [{status}] — {text[:80]}...")

            except Exception as e:
                print(f"  Block {i}: ERROR — {e}")
                total_blocks += 1

    # Summary
    avg = total_fn / total_blocks if total_blocks else 0
    print(f"\n{'='*50}")
    print(f"EVALUATION SUMMARY")
    print(f"{'='*50}")
    print(f"  Blocks evaluated:    {total_blocks}")
    print(f"  Total footnotes:     {total_fn}")
    print(f"  Avg FN/block:        {avg:.1f}")
    print(f"  Clean blocks (0-1):  {clean_blocks}/{total_blocks}")
    print(f"  Over-footnoted (>3): {over_footnoted}")
    print(f"  FN-in-FN errors:     {fn_in_fn}")
    print(f"  Trivial footnotes:   {trivial_count}")

    if trivial_examples:
        print(f"\n  Trivial examples:")
        for ex in trivial_examples[:10]:
            print(f"    - {ex}")

    return {
        "blocks": total_blocks,
        "total_fn": total_fn,
        "avg_fn": round(avg, 2),
        "clean_blocks": clean_blocks,
        "over_footnoted": over_footnoted,
        "fn_in_fn": fn_in_fn,
        "trivial": trivial_count,
    }


if __name__ == "__main__":
    start = time.time()
    result = evaluate()
    elapsed = time.time() - start
    print(f"\n  Time: {elapsed:.0f}s")
    print(f"\n  Result JSON: {json.dumps(result)}")
