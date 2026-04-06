#!/usr/bin/env python3
"""
DAG-Driven Pipeline CLI

Replaces the old orchestrate_translation_pipeline.py CLI with DAG-driven execution.

Usage:
    # Full run
    python -m cli.run_pipeline D60 --provider deepseek --workers 10

    # Resume from where it left off (auto-detect via progress DB)
    python -m cli.run_pipeline D60 --resume

    # Start from a specific node
    python -m cli.run_pipeline D60 --from cleanup_6a

    # Limit to specific chapters (for testing)
    python -m cli.run_pipeline D60 --chapters 3

    # Series mode — translate all works in a series
    python -m cli.run_pipeline --series "Condor Trilogy" --provider deepseek
    python -m cli.run_pipeline --series "Fox Volant Duology" --dry-run

    # Query progress (no run)
    python -m cli.run_pipeline D60 --status
    python -m cli.run_pipeline D60 --status --detail chapter
    python -m cli.run_pipeline D60 --status --detail block

    # Limit blocks per chapter
    python -m cli.run_pipeline D60 --chapters 1 --blocks 10        # first 10
    python -m cli.run_pipeline D60 --chapters 1 --blocks 5-15      # blocks 5-15
    python -m cli.run_pipeline D60 --chapters 1 --blocks 20-       # from 20 onward
"""

import time
from typing import List, Tuple


def _parse_volume_spec(spec: str, available: List[str]) -> List[str]:
    """Parse a volume specification into a list of volume letters.

    Args:
        spec: User input -- "a", "b", "all", "a-c", etc.
        available: Sorted list of volume letters from WorkInfo.volumes.

    Returns:
        List of volume letters to process.

    Raises:
        ValueError: If spec is invalid or references unknown volumes.
    """
    spec = spec.strip().lower()

    if spec == "all":
        return list(available)

    # Range: "a-c"
    if "-" in spec:
        parts = spec.split("-", 1)
        start_letter = parts[0].strip()
        end_letter = parts[1].strip()
        if start_letter not in available:
            raise ValueError(f"Volume '{start_letter}' not found. Available: {', '.join(available)}")
        if end_letter not in available:
            raise ValueError(f"Volume '{end_letter}' not found. Available: {', '.join(available)}")
        start_idx = available.index(start_letter)
        end_idx = available.index(end_letter)
        if start_idx > end_idx:
            raise ValueError(f"Invalid range: '{start_letter}' comes after '{end_letter}'")
        return available[start_idx:end_idx + 1]

    # Single letter: "a"
    if spec in available:
        return [spec]

    raise ValueError(f"Unknown volume '{spec}'. Available: {', '.join(available)} (or 'all', 'a-c')")


def _parse_range(s: str) -> Tuple[int, int]:
    """Parse a 1-based range string into (start, end) 1-based inclusive.

    '10'   -> (1, 10)   first 10 blocks
    '5-15' -> (5, 15)   blocks 5 through 15
    '20-'  -> (20, 0)   from block 20 onward (0 = no upper limit)
    """
    s = s.strip()
    if '-' in s:
        parts = s.split('-', 1)
        start = int(parts[0]) if parts[0] else 1
        end = int(parts[1]) if parts[1] else 0
        return (start, end)
    else:
        n = int(s)
        return (1, n)

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.progress_db import ProgressDB
from scripts.pipeline_runner import RunnerConfig, build_pipeline, run_series

logger = logging.getLogger(__name__)


def show_status(work_id: str, detail: str = "summary", db: ProgressDB = None):
    """Display progress status for a work."""
    if db is None:
        db = ProgressDB()

    progress = db.query_work(work_id)

    if progress.status == "not_started":
        print(f"\n  {work_id}: No pipeline runs found.\n")
        return

    print(f"\n  Work: {work_id}")
    print(f"  Run:  {progress.run_id}")
    print(f"  Status: {progress.status}")
    if progress.last_completed_stage:
        print(f"  Last completed: {progress.last_completed_stage}")
    if progress.current_stage:
        print(f"  Current stage:  {progress.current_stage}")
    print(f"  Events: {progress.total_events}")
    print()

    # Stage summary
    if progress.stages:
        print(f"  {'Stage':<25} {'Status':<12} {'Duration':<12} {'Chapters':<10} {'Blocks':<10}")
        print(f"  {'─'*25} {'─'*12} {'─'*12} {'─'*10} {'─'*10}")
        for s in progress.stages:
            dur = f"{s.duration_s:.1f}s" if s.duration_s else "—"
            ch = str(s.chapters_done) if s.chapters_done else "—"
            bl = str(s.blocks_done) if s.blocks_done else "—"
            print(f"  {s.stage:<25} {s.status:<12} {dur:<12} {ch:<10} {bl:<10}")
        print()

    # Chapter detail
    if detail == "chapter" and progress.stages:
        for stage_progress in progress.stages:
            if stage_progress.chapters_done == 0:
                continue
            chapters = db.query_chapters(work_id, stage_progress.stage,
                                          run_id=progress.run_id)
            if chapters:
                print(f"  {stage_progress.stage} — chapters:")
                for ch in chapters:
                    dur = f"{ch.duration_s:.1f}s" if ch.duration_s else "—"
                    print(f"    Ch {ch.chapter_num:>3}: {ch.status:<12} "
                          f"{ch.blocks_done} blocks  {dur}")
                print()

    # Run history
    runs = db.get_run_ids(work_id, limit=5)
    if len(runs) > 1:
        print(f"  Recent runs:")
        for r in runs:
            print(f"    {r['run_id']}  started={r['started_at']}  events={r['event_count']}")
        print()


def show_dag():
    """Show the DAG structure."""
    from workflows.translation_pipeline_dag import create_v2_pipeline_dag
    dag = create_v2_pipeline_dag()
    topo = dag.topological_sort()
    layers = dag._compute_layers()

    print("\n  Pipeline DAG (topological order):")
    print(f"  {'─'*50}")

    for layer_idx, layer in enumerate(layers):
        if len(layer) == 1:
            node = dag.nodes[layer[0]]
            print(f"  [{layer[0]:<25}] {node.display_name}")
        else:
            print(f"  ┌ parallel:")
            for nid in layer:
                node = dag.nodes[nid]
                print(f"  │  [{nid:<22}] {node.display_name}")
            print(f"  └")

    terminals = dag.get_terminal_nodes()
    print(f"\n  Terminal nodes: {', '.join(terminals)}")
    print(f"  Valid --from targets: {', '.join(topo)}")
    print()


def main():
    # Load .env FIRST — before any imports that might construct LLM clients
    try:
        import dotenv
        dotenv.load_dotenv()
    except ImportError:
        pass  # dotenv is optional

    parser = argparse.ArgumentParser(
        description="DAG-driven translation pipeline runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s D60                           Full run
  %(prog)s D60 --resume                  Auto-resume from last completed node
  %(prog)s D60 --from cleanup_6a         Start from cleanup (skip translation)
  %(prog)s D60 --chapters 3              Limit to first 3 chapters
  %(prog)s --series "Condor Trilogy"     Translate entire series in order
  %(prog)s --series "Fox Volant Duology" --dry-run
  %(prog)s A002 --split 2                 Split 120ch work into 2×60 volumes
  %(prog)s A002 --chapters-per-volume 60  Same as above
  %(prog)s A002 --split 2 --split-volume 2  Resume: process only volume 2
  %(prog)s D60 --status                  Show progress summary
  %(prog)s D60 --status --detail chapter Show per-chapter progress
  %(prog)s --dag                         Show pipeline DAG structure
        """,
    )

    parser.add_argument(
        "work_id", nargs="?",
        help="Work number (e.g. D60, D1379)",
    )
    parser.add_argument(
        "--series",
        help="Translate all works in a series by name (e.g. 'Condor Trilogy'). "
             "Kindle delivery deferred until entire series completes.",
    )
    parser.add_argument(
        "--volume", "-v",
        help="Volume letter (e.g. a), range (a-c), or 'all'. Required for multi-volume works.",
    )
    parser.add_argument(
        "--from", dest="from_node",
        help="Start from this DAG node (e.g. body, cleanup_6a, validation)",
    )
    parser.add_argument(
        "--resume", "-r", action="store_true",
        help="Auto-resume from last completed node (queries progress DB)",
    )
    parser.add_argument(
        "--chapters",
        help="Chapter range (1-based), e.g. '3' (first 3), '2-5' (chapters 2-5), '10-' (from 10 onward)",
    )
    parser.add_argument(
        "--blocks",
        help="Block range per chapter (1-based), e.g. '10' (first 10), '5-15' (blocks 5-15), '20-' (from 20 onward)",
    )

    # Provider / model settings
    parser.add_argument(
        "--provider",
        help="Translation provider (required for runs: deepseek, openai)",
    )
    parser.add_argument(
        "--model", "-m",
        help="Model name override",
    )
    parser.add_argument(
        "--cleanup-model",
        help="Lightweight model for footnote cleanup/scoring (e.g. gpt-4.1-nano)",
    )
    parser.add_argument(
        "--cleanup-provider",
        help="Provider for cleanup model (e.g. openai, deepseek). Defaults to CLEANUP_LLM_PROVIDER or LLM_PROVIDER.",
    )
    parser.add_argument(
        "--workers", "-w", type=int, default=50,
        help="Max parallel workers (default: 50)",
    )
    parser.add_argument(
        "--target-lang", default="en",
        help="Target language ISO code (default: en). E.g. fr, de, ja.",
    )
    parser.add_argument(
        "--temperature", type=float, default=0.3,
        help="Translation temperature (default: 0.3)",
    )

    parser.add_argument(
        "--kindle", action="store_true", default=False,
        help="Send EPUB to Kindle after build (default: off)",
    )
    parser.add_argument(
        "--include-source", action="store_true", default=False,
        help="Include original Chinese source text in EPUB (default: off — no Chinese in file)",
    )
    parser.add_argument(
        "--show-source", action="store_true", default=False,
        help="Make included Chinese source visible (default: hidden via CSS). Implies --include-source.",
    )

    # Volume splitting (for large single-file works)
    split_group = parser.add_mutually_exclusive_group()
    split_group.add_argument(
        "--split", type=int,
        help="Split work into N volumes of equal size (e.g. --split 2 for 120ch → 2×60)",
    )
    split_group.add_argument(
        "--chapters-per-volume", type=int,
        help="Split work into volumes of this many chapters (e.g. --chapters-per-volume 60)",
    )
    parser.add_argument(
        "--split-volume", type=int,
        help="Process only this split volume number (1-based). "
             "Use with --split to resume from a specific volume.",
    )

    # Status / info
    parser.add_argument(
        "--status", "-s", action="store_true",
        help="Show progress status (no run)",
    )
    parser.add_argument(
        "--detail", choices=["summary", "chapter", "block"],
        default="summary",
        help="Detail level for --status",
    )
    parser.add_argument(
        "--dag", action="store_true",
        help="Show DAG structure and valid node names",
    )

    # Other
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Don't write output files",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Verbose logging",
    )
    parser.add_argument(
        "--db-path",
        help="Override progress DB path",
    )
    parser.add_argument(
        "--log-file",
        help="Write logs to file (in addition to stderr)",
    )

    args = parser.parse_args()

    # Set up logging — force reconfigure even if root logger was already set up by imports
    log_level = logging.DEBUG if args.verbose else logging.INFO
    root = logging.getLogger()
    root.setLevel(log_level)
    # Clear any existing handlers from imports
    root.handlers.clear()
    fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    sh = logging.StreamHandler()
    sh.setLevel(log_level)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    # Auto-generate log file if not specified and we have a work_id
    log_file_path = args.log_file
    if not log_file_path and not args.status and not args.dag:
        _label = args.work_id or args.series
        if _label:
            from utils.environment_config import get_or_create_config
            _env = get_or_create_config()
            _env.log_dir.mkdir(parents=True, exist_ok=True)
            _ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            # Sanitize label for filename
            _safe = _label.replace(" ", "_").replace("/", "_")
            log_file_path = str(_env.log_dir / f"{_safe}_pipeline_{_ts}.log")

    if log_file_path:
        import io
        raw = open(log_file_path, "wb", buffering=0)
        stream = io.TextIOWrapper(raw, encoding="utf-8", write_through=True)
        fh = logging.StreamHandler(stream)
        fh.setLevel(log_level)
        fh.setFormatter(fmt)
        root.addHandler(fh)
        logger.info(f"Log file: {log_file_path}")

    # Show DAG
    if args.dag:
        show_dag()
        return 0

    # Need work_id or --series for everything else
    if not args.work_id and not args.series:
        parser.error("work_id or --series is required (unless using --dag)")

    # Initialize progress DB (read-only for status queries to avoid locking)
    db_path = Path(args.db_path) if args.db_path else None
    if args.status:
        if not args.work_id:
            parser.error("work_id is required for --status")
        db = ProgressDB(db_path, read_only=True)
        show_status(args.work_id, args.detail, db)
        db.close()
        return 0

    # Require --provider for actual pipeline runs
    if not args.provider:
        parser.error("--provider is required (e.g. --provider deepseek)")

    db = ProgressDB(db_path)

    # Resolve model from provider
    model = args.model
    if args.provider and not model:
        provider_models = {
            "deepseek": "deepseek-chat",
            "openai": "gpt-4.1-nano",
        }
        model = provider_models.get(args.provider, args.provider)

    # Build config
    config = RunnerConfig(
        model=model,
        provider=args.provider,
        cleanup_model=args.cleanup_model,
        cleanup_provider=args.cleanup_provider,
        temperature=args.temperature,
        max_workers=args.workers,
        target_lang=args.target_lang,
        dry_run=args.dry_run,
        verbose=args.verbose,
        include_source=args.include_source or args.show_source,
        show_source=args.show_source,
    )

    # --- Series mode ---
    if args.series:
        try:
            result = run_series(
                series_name=args.series,
                config=config,
                progress_db=db,
                from_node=args.from_node,
                resume=args.resume,
            )
        finally:
            db.close()

        # Series summary
        total_works = len(result.get("work_results", []))
        succeeded = sum(1 for r in result.get("work_results", []) if r.get("success"))
        print(f"\nSeries '{args.series}': {succeeded}/{total_works} works completed "
              f"in {result['duration_s']/60:.1f} minutes")
        if result.get("kindle_sent"):
            print(f"  Kindle: sent {len(result['kindle_sent'])} EPUBs")
        for wr in result.get("work_results", []):
            mark = "ok" if wr["success"] else "FAIL"
            vol_str = f" vol={wr['volume']}" if wr.get("volume") else ""
            print(f"  [{mark}] {wr['work_id']}{vol_str} — {wr.get('duration_s', 0)/60:.1f}min")

        return 0 if result["success"] else 1

    # --- Single work mode ---
    if not args.work_id:
        parser.error("work_id is required when not using --series")

    # Multi-volume guard: detect and validate volume selection
    from utils.library_resolver import resolve_work

    work_info = resolve_work(args.work_id)
    volumes_to_process = None  # None = single run with args.volume as-is

    if work_info and work_info.is_multi_volume:
        if not args.volume:
            vol_list = ", ".join(work_info.volumes)
            print(
                f"\n  Warning: {args.work_id} is a multi-volume work "
                f"with volumes: {vol_list}\n"
                f"\n"
                f"  You must specify which volume(s) to process:\n"
                f"    --volume a        Process volume a only\n"
                f"    --volume a-c      Process volumes a through c\n"
                f"    --volume all      Process all volumes sequentially\n",
                file=sys.stderr,
            )
            return 1
        else:
            try:
                parsed = _parse_volume_spec(args.volume, work_info.volumes)
            except ValueError as e:
                print(f"\n  Error: {e}\n", file=sys.stderr)
                return 1

            if len(parsed) > 1:
                volumes_to_process = parsed

    # --- Multi-volume iteration (--volume all or range) ---
    if volumes_to_process:
        logger.info(f"Processing {args.work_id} volumes: {', '.join(volumes_to_process)}")
        logger.info(f"  Cross-volume footnote dedup: enabled")

        all_results = []
        collected_manifests = []  # accumulate footnote manifests for cross-volume dedup
        overall_start = time.time()

        for vol in volumes_to_process:
            logger.info(f"\n{'─'*60}")
            logger.info(f"  Starting: {args.work_id} volume={vol}")
            if collected_manifests:
                total_ideo = sum(len(m.get("surviving_ideograms", {})) for m in collected_manifests)
                logger.info(f"  Cross-volume dedup: {total_ideo} ideograms from {len(collected_manifests)} prior volume(s)")
            logger.info(f"{'─'*60}")

            # Seed config with prior volume manifests for footnote dedup
            config.prior_volume_manifests = collected_manifests if collected_manifests else None
            runner = build_pipeline(config, db)
            try:
                chapter_range = _parse_range(args.chapters) if args.chapters else None
                block_range = _parse_range(args.blocks) if args.blocks else None

                result = runner.run(
                    work_id=args.work_id,
                    volume=vol,
                    from_node=args.from_node,
                    resume=args.resume,
                    chapter_range=chapter_range,
                    block_range=block_range,
                    skip_kindle=not args.kindle,
                )
                all_results.append({"volume": vol, **result})

                # Collect manifest for next volume's cross-volume dedup
                if result.get("footnote_manifest"):
                    collected_manifests.append(result["footnote_manifest"])

            except Exception as e:
                logger.error(f"Volume {vol} failed: {e}")
                all_results.append({"volume": vol, "success": False, "error": str(e), "duration_s": 0})

        db.close()

        overall_duration = time.time() - overall_start
        succeeded = sum(1 for r in all_results if r["success"])
        print(f"\n{args.work_id}: {succeeded}/{len(all_results)} volumes completed "
              f"in {overall_duration/60:.1f} minutes")
        for r in all_results:
            mark = "ok" if r["success"] else "FAIL"
            print(f"  [{mark}] volume {r['volume']} — {r.get('duration_s', 0)/60:.1f}min")

        return 0 if all(r["success"] for r in all_results) else 1

    # --- Volume splitting (large single-file works) ---
    if args.split or args.chapters_per_volume:
        # Load source to count chapters
        _tmp_runner = build_pipeline(config, db)
        _tmp_data = _tmp_runner._load_source(args.work_id, args.volume)
        if _tmp_data is None:
            print(f"\n  Error: Could not load source for {args.work_id}\n", file=sys.stderr)
            db.close()
            return 1

        total_chapters = len(_tmp_data.get("structure", {}).get("body", {}).get("chapters", []))
        del _tmp_data  # free memory

        if args.split:
            num_vols = args.split
            per_vol = (total_chapters + num_vols - 1) // num_vols
        else:
            per_vol = args.chapters_per_volume
            num_vols = (total_chapters + per_vol - 1) // per_vol

        # Compute chapter ranges for each split volume
        split_ranges = []
        for i in range(num_vols):
            start = i * per_vol + 1
            end = min((i + 1) * per_vol, total_chapters)
            split_ranges.append((start, end))

        logger.info(f"Splitting {args.work_id} ({total_chapters} chapters) into {num_vols} volumes:")
        for i, (s, e) in enumerate(split_ranges):
            logger.info(f"  Volume {i+1}: chapters {s}-{e} ({e - s + 1} chapters)")

        # Determine which volumes to process
        if args.split_volume:
            if args.split_volume < 1 or args.split_volume > num_vols:
                print(f"\n  Error: --split-volume {args.split_volume} out of range (1-{num_vols})\n",
                      file=sys.stderr)
                db.close()
                return 1
            vols_to_run = [args.split_volume]
        else:
            vols_to_run = list(range(1, num_vols + 1))

        # Load prior manifests from disk for resume
        from pathlib import Path
        manifest_dir = config.wip_dir / "manifests"
        collected_manifests = []
        first_vol = vols_to_run[0]
        if first_vol > 1:
            # Load manifests from prior split volumes
            for prior_vol in range(1, first_vol):
                manifest_path = manifest_dir / f"{args.work_id}_split{prior_vol}_footnote_manifest.json"
                if manifest_path.exists():
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        collected_manifests.append(json.load(f))
                    logger.info(f"  Loaded prior manifest: {manifest_path.name}")
                else:
                    logger.warning(f"  Prior manifest not found: {manifest_path.name} "
                                   f"(cross-volume dedup may miss terms from volume {prior_vol})")

        logger.info(f"  Cross-volume footnote dedup: {'enabled' if collected_manifests else 'will accumulate'}")

        all_results = []
        overall_start = time.time()

        for vol_num in vols_to_run:
            vol_idx = vol_num - 1
            ch_start, ch_end = split_ranges[vol_idx]

            logger.info(f"\n{'─'*60}")
            logger.info(f"  Split volume {vol_num}/{num_vols}: chapters {ch_start}-{ch_end}")
            if collected_manifests:
                total_ideo = sum(len(m.get("surviving_ideograms", {})) for m in collected_manifests)
                logger.info(f"  Cross-volume dedup: {total_ideo} ideograms from {len(collected_manifests)} prior volume(s)")
            logger.info(f"{'─'*60}")

            config.prior_volume_manifests = collected_manifests if collected_manifests else None
            # Inject split metadata so pipeline can set volume info on data
            config._split_volume_num = vol_num
            config._split_total_volumes = num_vols
            runner = build_pipeline(config, db)

            try:
                block_range = _parse_range(args.blocks) if args.blocks else None
                result = runner.run(
                    work_id=args.work_id,
                    volume=args.volume,
                    from_node=args.from_node,
                    resume=args.resume,
                    chapter_range=(ch_start, ch_end),
                    block_range=block_range,
                    skip_kindle=not args.kindle,
                )
                all_results.append({"split_volume": vol_num, **result})

                if result.get("footnote_manifest"):
                    collected_manifests.append(result["footnote_manifest"])

            except Exception as e:
                logger.error(f"Split volume {vol_num} failed: {e}")
                all_results.append({"split_volume": vol_num, "success": False, "error": str(e), "duration_s": 0})

        db.close()

        overall_duration = time.time() - overall_start
        succeeded = sum(1 for r in all_results if r["success"])
        print(f"\n{args.work_id}: {succeeded}/{len(all_results)} split volumes completed "
              f"in {overall_duration/60:.1f} minutes")
        for r in all_results:
            mark = "ok" if r["success"] else "FAIL"
            vol = r.get("split_volume", "?")
            print(f"  [{mark}] volume {vol} — {r.get('duration_s', 0)/60:.1f}min")

        return 0 if all(r["success"] for r in all_results) else 1

    # --- Single volume run ---
    runner = build_pipeline(config, db)

    try:
        # Parse ranges
        chapter_range = _parse_range(args.chapters) if args.chapters else None
        block_range = _parse_range(args.blocks) if args.blocks else None

        result = runner.run(
            work_id=args.work_id,
            volume=args.volume,
            from_node=args.from_node,
            resume=args.resume,
            chapter_range=chapter_range,
            block_range=block_range,
            skip_kindle=not args.kindle,
        )
    finally:
        db.close()

    # Print summary
    if result["success"]:
        print(f"\nPipeline completed successfully in {result['duration_s']/60:.1f} minutes")
    else:
        print(f"\nPipeline FAILED after {result['duration_s']/60:.1f} minutes")
        for stage in result.get("stages", []):
            if not stage["success"]:
                print(f"  Failed at: {stage['node']} — {stage.get('error', 'unknown')}")

    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
