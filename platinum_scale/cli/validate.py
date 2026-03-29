"""CLI for Platinum Scale strip validation.

Usage:
    python -m platinum_scale.cli.validate --strips-dir /path/to/ocr_strips/三俠五義_validation/
    python -m platinum_scale.cli.validate --strips-dir /path/to/strips/ --resume
    python -m platinum_scale.cli.validate --strips-dir /path/to/strips/ --report
    python -m platinum_scale.cli.validate --strips-dir /path/to/strips/ --show-disagreements
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Ensure platinum_scale is importable when run from inside the package
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from platinum_scale.config.defaults import COST_PER_1M_INPUT, COST_PER_1M_OUTPUT, MAX_WORKERS
from platinum_scale.validators.strip_validator import validate_book


def _load_existing_validations(strips_dir: Path) -> list[dict]:
    """Load all existing validation.json files for reporting."""
    results = []

    vol_dirs = sorted(d for d in strips_dir.iterdir() if d.is_dir() and d.name.startswith("vol"))
    if not vol_dirs:
        vol_dirs = [strips_dir]

    for vol_dir in vol_dirs:
        page_dirs = sorted(
            d for d in vol_dir.iterdir()
            if d.is_dir() and d.name.startswith("page_")
        )
        for page_dir in page_dirs:
            val_path = page_dir / "validation.json"
            if val_path.exists():
                with open(val_path, "r", encoding="utf-8") as f:
                    results.append(json.load(f))

    return results


def cmd_validate(args: argparse.Namespace) -> None:
    """Main validation command."""
    strips_dir = Path(args.strips_dir)
    if not strips_dir.exists():
        print(f"Strips directory not found: {strips_dir}")
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # Handle --show-disagreements (report-only, no API calls)
    if args.show_disagreements:
        pages = _load_existing_validations(strips_dir)
        if not pages:
            print("No validation results found. Run validation first.")
            return

        disagreements = []
        for page in pages:
            for strip in page.get("strips", []):
                if not strip.get("agreement") and strip.get("status") == "validated":
                    disagreements.append({
                        "page": page.get("page_label"),
                        "strip": strip.get("strip_file"),
                        "sg": strip.get("sg_classification"),
                        "nano": strip.get("nano_classification"),
                        "chars": strip.get("char_estimate"),
                        "reason": strip.get("reason"),
                    })

        if not disagreements:
            print("No disagreements — Silver Gauge and nano agree on all strips.")
        else:
            print(f"Found {len(disagreements)} disagreements:\n")
            for d in disagreements:
                print(f"  {d['page']} / {d['strip']}")
                print(f"    Silver Gauge: {d['sg']}  →  nano: {d['nano']} ({d['chars']} chars)")
                print(f"    Reason: {d['reason']}")
        return

    # Handle --report (show summary of existing validations)
    if args.report:
        pages = _load_existing_validations(strips_dir)
        if not pages:
            print("No validation results found. Run validation first.")
            return

        total_strips = sum(p.get("validated", 0) for p in pages)
        total_agree = sum(p.get("agreements", 0) for p in pages)
        total_disagree = sum(p.get("disagreements", 0) for p in pages)
        total_input = sum(p.get("total_input_tokens", 0) for p in pages)
        total_output = sum(p.get("total_output_tokens", 0) for p in pages)
        cost = (total_input * COST_PER_1M_INPUT + total_output * COST_PER_1M_OUTPUT) / 1_000_000

        # Classification distribution from nano
        from collections import Counter
        nano_classes = Counter()
        for page in pages:
            for strip in page.get("strips", []):
                nano_classes[strip.get("nano_classification", "unknown")] += 1

        print(f"Validation Report for {strips_dir}")
        print(f"  Pages validated:   {len(pages)}")
        print(f"  Strips validated:  {total_strips}")
        print(f"  Agreement:         {total_agree}/{total_strips} "
              f"({total_agree/total_strips*100:.0f}%)" if total_strips else "")
        print(f"  Disagreements:     {total_disagree}")
        print(f"  Tokens:            {total_input:,} input + {total_output:,} output")
        print(f"  Cost:              ${cost:.4f}")
        print(f"\n  Nano classifications:")
        for cls, count in nano_classes.most_common():
            print(f"    {cls}: {count}")
        return

    # Run validation
    print(f"Validating strips in {strips_dir} using {args.model or 'gpt-4.1-nano'}...")
    results = asyncio.run(validate_book(
        strips_dir,
        resume=args.resume,
        max_workers=args.workers or MAX_WORKERS,
    ))

    if not results:
        print("No new pages to validate (all already done, or no strips found).")
        return

    # Summary
    total_strips = sum(p.get("validated", 0) for p in results)
    total_agree = sum(p.get("agreements", 0) for p in results)
    total_disagree = sum(p.get("disagreements", 0) for p in results)
    total_input = sum(p.get("total_input_tokens", 0) for p in results)
    total_output = sum(p.get("total_output_tokens", 0) for p in results)
    cost = (total_input * COST_PER_1M_INPUT + total_output * COST_PER_1M_OUTPUT) / 1_000_000

    print(f"\nValidated {len(results)} pages, {total_strips} strips")
    print(f"  Agreement: {total_agree}/{total_strips}")
    print(f"  Disagreements: {total_disagree}")
    print(f"  Cost: ${cost:.4f}")

    # Print per-page results
    for page in results:
        disagree_count = page.get("disagreements", 0)
        flag = f" *** {disagree_count} DISAGREE ***" if disagree_count > 0 else ""
        print(f"  {page.get('page_label')}: {page.get('validated')} strips, "
              f"{page.get('agreements')} agree{flag}")

    if total_disagree > 0:
        print(f"\nRun with --show-disagreements to see details.")


def main():
    parser = argparse.ArgumentParser(description="Platinum Scale — strip validation via nano")
    parser.add_argument("--strips-dir", required=True, help="Directory of sliced strips")
    parser.add_argument("--resume", action="store_true", help="Skip already-validated pages")
    parser.add_argument("--report", action="store_true", help="Show validation report (no API calls)")
    parser.add_argument("--show-disagreements", action="store_true", help="Show SG/nano disagreements")
    parser.add_argument("--workers", type=int, help=f"Max concurrent API calls (default {MAX_WORKERS})")
    parser.add_argument("--model", help="Override model (default gpt-4.1-nano)")

    args = parser.parse_args()
    cmd_validate(args)


if __name__ == "__main__":
    main()
