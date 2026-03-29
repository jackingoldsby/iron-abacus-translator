"""CLI for Ivory Helm iterative OCR orchestration.

Usage:
    # Run with book-specific config
    python -m ivory_helm.cli.run run --book 三俠五義 --strips-dir /path/to/strips/ --images-dir /path/to/images/

    # Resume
    python -m ivory_helm.cli.run run --book 三俠五義 --strips-dir /path/to/strips/ --resume

    # List available book configs
    python -m ivory_helm.cli.run configs

    # Show iteration report
    python -m ivory_helm.cli.run report --strips-dir /path/to/strips/
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from ivory_helm.config.book_config import list_book_configs, load_config
from ivory_helm.orchestrator.loop import _load_env, _preflight_check, process_book


def _load_reports(strips_dir: Path) -> list[dict]:
    """Load all iteration_report.json files."""
    reports = []
    vol_dirs = sorted(d for d in strips_dir.iterdir() if d.is_dir() and d.name.startswith("vol"))
    if not vol_dirs:
        vol_dirs = [strips_dir]

    for vol_dir in vol_dirs:
        for page_dir in sorted(d for d in vol_dir.iterdir()
                               if d.is_dir() and d.name.startswith("page_")):
            report_path = page_dir / "iteration_report.json"
            if report_path.exists():
                with open(report_path, "r", encoding="utf-8") as f:
                    reports.append(json.load(f))
    return reports


def cmd_run(args: argparse.Namespace) -> None:
    """Run the iterative pipeline."""
    strips_dir = Path(args.strips_dir)
    images_dir = Path(args.images_dir) if args.images_dir else None
    book_id = args.book

    if not strips_dir.exists():
        print(f"Strips directory not found: {strips_dir}")
        sys.exit(1)

    # Preflight-only mode: load env, run checks, exit
    if args.preflight_only:
        _load_env()
        try:
            page_count, _engine = _preflight_check(strips_dir)
            print(f"Preflight OK: {page_count} pages, PaddleOCR ready, OpenAI reachable")
        except RuntimeError as e:
            print(str(e))
            sys.exit(1)
        return

    cfg = load_config(book_id)

    print(f"Ivory Helm: iterative OCR pipeline")
    print(f"  Book:   {cfg.book_id or '(default config)'}")
    print(f"  Strips: {strips_dir}")
    if images_dir:
        print(f"  Images: {images_dir} (re-slicing enabled)")
    else:
        print(f"  No images dir — re-slicing disabled")
    print(f"  Max iterations: {cfg.ivory_helm.max_iterations}")
    print(f"  Strategies: {len(cfg.ivory_helm.reslice_strategies)}")
    print(f"  SG: k={cfg.silver_gauge.smooth_k}, t={cfg.silver_gauge.threshold_pct}, "
          f"cols={cfg.silver_gauge.expected_columns_min}-{cfg.silver_gauge.expected_columns_max}")
    print(f"  BM: lang={cfg.bronze_mirror.ocr_lang}, "
          f"headers={len(cfg.bronze_mirror.header_patterns)} patterns, "
          f"fixes={len(cfg.bronze_mirror.ocr_fixes)}")

    reports = asyncio.run(process_book(
        strips_dir=strips_dir,
        source_images_dir=images_dir,
        resume=args.resume,
        book_id=book_id,
    ))

    passed = sum(1 for r in reports if r.get("final_status") == "pass")
    best_effort = sum(1 for r in reports if r.get("final_status") == "best_effort")
    total_iterations = sum(len(r.get("iterations", [])) for r in reports)

    print(f"\nResults: {len(reports)} pages")
    print(f"  Passed:      {passed}")
    print(f"  Best effort: {best_effort}")
    print(f"  Total iterations: {total_iterations}")

    multi = [r for r in reports if len(r.get("iterations", [])) > 1]
    if multi:
        print(f"\nPages needing re-slicing ({len(multi)}):")
        for r in multi:
            iters = len(r["iterations"])
            status = r["final_status"]
            last = r["iterations"][-1].get("assessment", {})
            print(f"  {r['page_label']}: {iters} iterations → {status} "
                  f"(chars={last.get('total_chars', '?')}, "
                  f"kept={last.get('kept_ratio', '?')})")


def cmd_report(args: argparse.Namespace) -> None:
    """Show iteration results."""
    strips_dir = Path(args.strips_dir)
    reports = _load_reports(strips_dir)

    if not reports:
        print("No iteration reports found.")
        return

    passed = sum(1 for r in reports if r.get("final_status") == "pass")
    best_effort = sum(1 for r in reports if r.get("final_status") == "best_effort")
    total_iters = sum(len(r.get("iterations", [])) for r in reports)

    print(f"Iteration Report: {strips_dir}")
    print(f"  Pages:           {len(reports)}")
    print(f"  Passed:          {passed}")
    print(f"  Best effort:     {best_effort}")
    print(f"  Total iterations:{total_iters}")
    print(f"  Avg iterations:  {total_iters/len(reports):.1f}")

    by_iters = sorted(reports, key=lambda r: len(r.get("iterations", [])), reverse=True)
    print(f"\nMost problematic pages:")
    for r in by_iters[:10]:
        iters = len(r.get("iterations", []))
        if iters <= 1:
            break
        last = r["iterations"][-1].get("assessment", {})
        print(f"  {r['page_label']}: {iters} iterations, "
              f"status={r['final_status']}, "
              f"reason={last.get('reason', 'ok')}")


def cmd_configs(args: argparse.Namespace) -> None:
    """List available book configurations."""
    configs = list_book_configs()
    if not configs:
        print("No book-specific configs found. Only default.yaml exists.")
        print("Create a new one: ivory_helm/config/books/<book_name>.yaml")
        return

    print(f"Available book configs ({len(configs)}):")
    for name in configs:
        cfg = load_config(name)
        md = cfg.metadata
        print(f"  {name}")
        if md.title:
            print(f"    {md.title} — {md.creator or 'unknown author'}")
        sg = cfg.silver_gauge
        print(f"    SG: k={sg.smooth_k}, t={sg.threshold_pct}, "
              f"cols={sg.expected_columns_min}-{sg.expected_columns_max}")
        bm = cfg.bronze_mirror
        print(f"    BM: {len(bm.header_patterns)} header patterns, "
              f"{len(bm.ocr_fixes)} OCR fixes")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Ivory Helm — iterative OCR orchestration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_run = subparsers.add_parser("run", help="Run iterative pipeline")
    p_run.add_argument("--book", help="Book ID (loads config/books/<book>.yaml)")
    p_run.add_argument("--strips-dir", required=True, help="Silver Gauge output directory")
    p_run.add_argument("--images-dir", help="Preprocessed page images (enables re-slicing)")
    p_run.add_argument("--resume", action="store_true", help="Skip pages that already passed")
    p_run.add_argument("--preflight-only", action="store_true",
                       help="Run preflight checks only (env, PaddleOCR, data, OpenAI), then exit")

    p_report = subparsers.add_parser("report", help="Show iteration results")
    p_report.add_argument("--strips-dir", required=True)

    p_configs = subparsers.add_parser("configs", help="List available book configurations")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "configs":
        cmd_configs(args)


if __name__ == "__main__":
    main()
