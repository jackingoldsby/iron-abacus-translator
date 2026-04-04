#!/usr/bin/env python3
"""
CLI for Chapter Consistency Review

Reviews translated chapters for cross-block consistency issues:
tense shifts, gender pronoun confusion, register breaks, missing
footnotes, and pinyin errors.

Usage:
    python -m cli.review --input translated_D60.json --chapter 3
    python -m cli.review --input translated_D60.json --chapters 1,3,5
    python -m cli.review --input translated_D60.json
    python -m cli.review --input translated_D60.json --output review_report.json
    python -m cli.review --input translated_D60.json --dry-run
    python -m cli.review --input translated_D60.json --apply
    python -m cli.review --input translated_D60.json --apply --apply-categories tense,gender,pinyin
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from processors.consistency_reviewer import ConsistencyReviewer

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Review translated chapters for cross-block consistency issues",
    )
    parser.add_argument("--input", "-i", required=True,
                        help="Path to translated JSON file")
    parser.add_argument("--chapter", "-c", type=int, default=None,
                        help="Review a single chapter (1-based index)")
    parser.add_argument("--chapters", type=str, default=None,
                        help="Comma-separated list of chapter indices to review (e.g. 1,3,5)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output path for review report JSON (default: stdout)")
    parser.add_argument("--model", type=str, default="deepseek-chat",
                        help="LLM model to use (default: deepseek-chat)")
    parser.add_argument("--provider", type=str, default="deepseek",
                        help="LLM provider (default: deepseek)")
    parser.add_argument("--workers", type=int, default=5,
                        help="Max parallel workers for chapter review (default: 5)")
    parser.add_argument("--temperature", type=float, default=0.2,
                        help="LLM temperature (default: 0.2)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be reviewed without calling the LLM")
    parser.add_argument("--apply", action="store_true",
                        help="Apply findings to the input file (saves modified JSON)")
    parser.add_argument("--apply-categories", type=str, default=None,
                        help="Comma-separated categories to apply (default: all). "
                             "Options: tense,gender,style,footnote,pinyin")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return 1

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Determine work_id from metadata or filename
    work_id = data.get("metadata", {}).get("work_number", "")
    if not work_id:
        work_id = input_path.stem.split("_")[1] if "_" in input_path.stem else input_path.stem

    # Parse chapter selection
    chapter_list = None
    if args.chapter is not None:
        chapter_list = [args.chapter]
    elif args.chapters:
        chapter_list = [int(c.strip()) for c in args.chapters.split(",")]

    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
    if not chapters:
        logger.error("No chapters found in input file")
        return 1

    # Dry run — just show what would be reviewed
    if args.dry_run:
        selected = chapter_list or list(range(1, len(chapters) + 1))
        print(f"Work: {work_id}")
        print(f"Total chapters: {len(chapters)}")
        print(f"Chapters to review: {selected}")
        for idx in selected:
            if idx < 1 or idx > len(chapters):
                print(f"  Chapter {idx}: OUT OF RANGE")
                continue
            ch = chapters[idx - 1]
            blocks = ch.get("content_blocks", [])
            translated = sum(1 for b in blocks if b.get("translated_content"))
            title = ch.get("title", ch.get("heading", f"Chapter {idx}"))
            print(f"  Chapter {idx}: {title} ({translated}/{len(blocks)} blocks translated)")
        return 0

    # Run review
    reviewer = ConsistencyReviewer(
        model=args.model,
        provider=args.provider,
        temperature=args.temperature,
        max_workers=args.workers,
    )

    reports = reviewer.review_work(data, work_id, chapters=chapter_list)

    # Summarize
    total_findings = sum(r["summary"]["total_findings"] for r in reports)
    print(f"\nReview complete: {total_findings} findings across {len(reports)} chapters")
    for r in reports:
        if r["summary"]["total_findings"] > 0:
            cats = ", ".join(f"{k}={v}" for k, v in r["summary"]["by_category"].items())
            print(f"  Chapter {r['chapter']}: {r['summary']['total_findings']} findings ({cats})")

    # Output report
    report_data = {
        "work_id": work_id,
        "model": args.model,
        "reviewed_at": reports[0]["reviewed_at"] if reports else None,
        "total_findings": total_findings,
        "chapter_reports": reports,
    }

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        print(f"Report saved to: {output_path}")
    else:
        print(json.dumps(report_data, ensure_ascii=False, indent=2))

    # Apply findings if requested
    if args.apply and total_findings > 0:
        apply_cats = None
        if args.apply_categories:
            apply_cats = [c.strip() for c in args.apply_categories.split(",")]

        data = reviewer.apply_findings(data, reports, auto_apply=apply_cats)

        with open(input_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Applied {total_findings} findings to: {input_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
