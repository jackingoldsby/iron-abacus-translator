#!/usr/bin/env python3
"""
Quick prompt test: translate chapter 1 from a book and report quality metrics.

Usage:
    python scripts/test_v2_chapter1.py --input path/to/cleaned.json
"""

import sys
import json
import re
import time
import argparse
from pathlib import Path
from dataclasses import asdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "iron_abacus_translator"))

from dotenv import load_dotenv
load_dotenv()

from utils.footnote_context import FootnoteContextAccumulator
from wrappers.content_block_translation_wrapper import ContentBlockTranslationWrapper
from utils.remove_trivial_footnotes import TrivialFootnoteRemover, TrivialityConfig
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument("--model", default="gpt-4.1-nano")
    parser.add_argument("--chapter", "-c", type=int, default=1, help="Chapter number to translate (1-indexed)")
    args = parser.parse_args()

    input_file = Path(args.input)
    with open(input_file) as f:
        book_data = json.load(f)

    chapters = book_data.get("structure", {}).get("body", {}).get("chapters", [])
    if not chapters:
        print("No chapters found")
        return 1

    ch_idx = args.chapter - 1
    if ch_idx < 0 or ch_idx >= len(chapters):
        print(f"Chapter {args.chapter} out of range (1-{len(chapters)})")
        return 1

    ch = chapters[ch_idx]
    blocks = ch.get("content_blocks", [])
    translatable = [
        b for b in blocks
        if b.get("type") in ["text", "paragraph", "narrative", "dialogue", "verse",
                              "document", "thought", "descriptive"]
        and b.get("content", "").strip()
    ]

    title = ch.get("title", "Untitled")
    work = book_data.get("meta", {}).get("title", input_file.stem)
    print(f"\n{'='*70}")
    print(f" {work} — Chapter {args.chapter}: {title}")
    print(f" {len(translatable)} translatable blocks")
    print(f"{'='*70}")

    accumulator = FootnoteContextAccumulator()
    wrapper = ContentBlockTranslationWrapper(
        accumulator=accumulator,
        model=args.model,
        temperature=0.3,
        max_retries=2,
        timeout=120,
    )

    start = time.time()
    results = []

    for idx, block in enumerate(translatable):
        block_id = block.get("id", f"block_{idx}")
        try:
            result = wrapper.execute(
                content_text_id=idx + 1,
                content_source_text=block["content"],
                work_id="TEST",
                chapter_num=1,
            )
            if result.success:
                annotated = result.translated_data.get("translated_annotated_content", {})
                block["translated_content"] = annotated.get("annotated_content_text", "")
                block["footnotes"] = [
                    {
                        "key": fn["footnote_key"],
                        "ideogram": fn["footnote_details"]["footnote_ideogram"],
                        "pinyin": fn["footnote_details"]["footnote_pinyin"],
                        "explanation": fn["footnote_details"]["footnote_explanation"],
                    }
                    for fn in annotated.get("content_footnotes", [])
                ]
                block["content_type"] = annotated.get("content_type", "narrative")
                results.append(block)
            else:
                logger.error(f"Block {block_id} failed")
                results.append(block)
        except Exception as e:
            logger.error(f"Block {block_id}: {e}")
            results.append(block)

    elapsed = time.time() - start

    # --- Metrics ---
    translated = [b for b in results if b.get("translated_content")]
    total_fn = sum(len(b.get("footnotes", [])) for b in translated)
    avg_fn = total_fn / len(translated) if translated else 0
    over3 = sum(1 for b in translated if len(b.get("footnotes", [])) > 3)
    clean = sum(1 for b in translated if len(b.get("footnotes", [])) <= 1)

    # Orphan markers
    orphan_blocks = 0
    for b in translated:
        text = b.get("translated_content", "")
        markers = set(re.findall(r"\[(\d+)\]", text))
        fn_keys = set(str(fn.get("key")) for fn in b.get("footnotes", []))
        if markers - fn_keys:
            orphan_blocks += 1

    # Name translation check (look for English words before Chinese-looking names)
    name_issues = []
    for b in translated:
        text = b.get("translated_content", "")
        # Pattern: English word + capital letter that looks like a translated name
        if re.search(r'\b(Cloud|Snow|Jade|Iron|Gold|Silver|Dragon|Phoenix|Flower|Moon|Star|Wind|Rain|Thunder|Ice|Fire|Stone|River|Mountain|Sky|Heavenly|Flying)\s+[A-Z]', text):
            name_issues.append(b.get("id"))

    # Tone mark check
    no_tones = []
    for b in translated:
        text = b.get("translated_content", "")
        # Find capitalized multi-word names without any tone marks
        names = re.findall(r'([A-Z][a-z]+ [A-Z][a-z]+)', text)
        for name in names:
            if not re.search(r'[āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]', name):
                no_tones.append(name)

    # Trivial footnote check
    trivial_terms = {'sigh', 'both hands', 'mountain path', 'firewood', 'moss', 'young woman',
                     'skirt', 'chair', 'table', 'gate', 'door', 'wine', 'tea', 'mask',
                     'shadowy', 'gray cloth', 'walking', 'running', 'sitting'}
    trivial_fn = 0
    trivial_examples = []
    for b in translated:
        for fn in b.get("footnotes", []):
            expl = fn.get("explanation", "").lower()
            for t in trivial_terms:
                if t in expl:
                    trivial_fn += 1
                    trivial_examples.append(f"{fn['ideogram']}: {expl[:60]}")
                    break

    print(f"\n{'='*70}")
    print(f" RESULTS")
    print(f"{'='*70}")
    print(f"  Time:            {elapsed:.0f}s ({elapsed/60:.1f}m)")
    print(f"  Translated:      {len(translated)}/{len(translatable)} blocks")
    print(f"  Total footnotes: {total_fn}")
    print(f"  Avg FN/block:    {avg_fn:.1f}")
    print(f"  Clean (0-1 FN):  {clean}/{len(translated)} ({clean/len(translated)*100:.0f}%)")
    print(f"  Over-footnoted:  {over3} blocks (>3 FN)")
    print(f"  Orphan markers:  {orphan_blocks} blocks")
    print(f"  Translated names:{len(name_issues)} blocks (should be 0)")
    print(f"  Names w/o tones: {len(set(no_tones))} unique")
    print(f"  Trivial FN:      {trivial_fn}")

    if name_issues:
        print(f"\n  Name translation issues in: {name_issues[:5]}")
    if no_tones:
        print(f"  Names missing tones: {list(set(no_tones))[:10]}")
    if trivial_examples:
        print(f"  Trivial FN examples:")
        for ex in trivial_examples[:5]:
            print(f"    - {ex}")

    # Sample 3 blocks
    print(f"\n{'='*70}")
    print(f" SAMPLES")
    print(f"{'='*70}")
    samples = []
    if len(translated) >= 6:
        samples = [translated[1], translated[len(translated)//2], translated[-2]]
    else:
        samples = translated[:3]

    for b in samples:
        print(f"\n  [{b.get('content_type','?')}] {b.get('id','')}")
        print(f"  SRC: {b.get('content','')[:120]}...")
        print(f"  ENG: {b.get('translated_content','')[:250]}")
        fns = b.get("footnotes", [])
        if fns:
            for fn in fns[:3]:
                print(f"    [{fn['key']}] {fn['ideogram']} — {fn['explanation'][:80]}")

    # Save output
    stem = input_file.stem.replace("cleaned_", "")
    out = Path(f"translation_data/test_v2/{stem}_ch{args.chapter}.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    output_data = {
        "meta": book_data.get("meta", {}),
        "chapter": {
            "title": title,
            "content_blocks": results,
        },
        "metrics": {
            "translated": len(translated),
            "total_fn": total_fn,
            "avg_fn": round(avg_fn, 1),
            "clean_blocks": clean,
            "over_footnoted": over3,
            "orphan_blocks": orphan_blocks,
            "name_issues": len(name_issues),
            "no_tone_names": len(set(no_tones)),
            "trivial_fn": trivial_fn,
            "elapsed_seconds": round(elapsed),
        },
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"\n  Saved: {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
