#!/usr/bin/env python3
"""
Parallel Work Runner for Translation Pipeline

CLI for ad-hoc translation runs of selected works, typically 5-6 in parallel.
Each work runs its own DAG pipeline instance. Multi-volume works share
an accumulator across volumes (sequential within work).

Usage:
    # Translate specific works
    python scripts/translate_works_parallel.py D55 D1379 I1046 --max-parallel 5

    # Resume interrupted runs
    python scripts/translate_works_parallel.py D55 D1379 --resume

    # Translate specific volume
    python scripts/translate_works_parallel.py D1379 --volume a
"""

import sys
import json
import argparse
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.pipeline_runner import build_pipeline, RunnerConfig
from utils.progress_db import ProgressDB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Lock for thread-safe console output
_print_lock = Lock()


def _find_volumes(source_dir: Path, work_number: str) -> List[Optional[str]]:
    """
    Find all volume files for a work.

    Returns list of volume identifiers (e.g., ['a', 'b', 'c']) or [None]
    if the work has no volume suffix.
    """
    pattern = f"*{work_number}*.json"
    matches = sorted(source_dir.glob(pattern))

    if not matches:
        return []

    if len(matches) == 1:
        return [None]  # Single volume, no suffix needed

    # Extract volume letters from filenames
    volumes = []
    for match in matches:
        name = match.stem
        # Try to find volume letter after work number
        idx = name.find(work_number) + len(work_number)
        if idx < len(name):
            vol_char = name[idx]
            if vol_char.isalpha():
                volumes.append(vol_char)
            else:
                volumes.append(None)
        else:
            volumes.append(None)

    return volumes if volumes else [None]


def translate_single_work(
    work_number: str,
    config: RunnerConfig,
    resume: bool = False,
    volume: Optional[str] = None,
    from_node: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Translate a single work (all volumes sequentially).

    Multi-volume works are processed sequentially so that footnote
    deduplication carries across volumes.

    Args:
        work_number: Work number (e.g., "D1379")
        config: Runner config
        resume: Whether to resume from checkpoint
        volume: Specific volume to translate (None = all volumes)
        from_node: Start from this DAG node (skip predecessors)

    Returns:
        Result dict with per-volume results
    """
    start_time = datetime.now()

    # Determine volumes to process
    if volume:
        volumes = [volume]
    else:
        volumes = _find_volumes(config.source_dir, work_number)

    if not volumes:
        return {
            "work_number": work_number,
            "success": False,
            "error": "No source files found",
        }

    with _print_lock:
        logger.info(
            f"[{work_number}] Starting: {len(volumes)} volume(s) "
            f"{'(resuming)' if resume else ''}"
        )

    volume_results = []
    for vol in volumes:
        vol_label = vol or "single"
        with _print_lock:
            logger.info(f"[{work_number}] Processing volume {vol_label}...")

        try:
            runner = build_pipeline(config)
            result = runner.run(
                work_id=work_number,
                volume=vol,
                resume=resume,
                from_node=from_node,
            )
            volume_results.append(result)

        except Exception as e:
            logger.error(f"[{work_number}] Volume {vol_label} failed: {e}")
            volume_results.append({
                "success": False,
                "work_number": work_number,
                "volume": vol,
                "error": str(e),
            })

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    all_success = all(r.get("success", False) for r in volume_results)

    with _print_lock:
        status = "SUCCESS" if all_success else "PARTIAL"
        logger.info(
            f"[{work_number}] {status}: {len(volumes)} volumes in "
            f"{duration/60:.1f} min"
        )

    return {
        "work_number": work_number,
        "success": all_success,
        "volumes": len(volumes),
        "volume_results": volume_results,
        "duration_seconds": duration,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Translate multiple works in parallel"
    )
    parser.add_argument(
        "work_numbers",
        nargs="+",
        help="Work numbers to translate (e.g., D55 D1379 I1046)",
    )
    parser.add_argument(
        "--max-parallel",
        type=int, default=5,
        help="Maximum works to translate in parallel (default: 5)",
    )
    parser.add_argument(
        "--resume", "-r",
        action="store_true",
        help="Resume interrupted translations from checkpoints",
    )
    parser.add_argument(
        "--volume", "-v",
        help="Translate specific volume only (e.g., a)",
    )
    parser.add_argument(
        "--from-node",
        help="Start from this DAG node (e.g., cleanup_6a)",
    )
    parser.add_argument(
        "--max-workers",
        type=int, default=5,
        help="Parallel workers per work for body translation (default: 5)",
    )
    parser.add_argument(
        "--model",
        help="Translation model (default from env config)",
    )
    parser.add_argument(
        "--provider",
        help="Translation provider (e.g., deepseek, openai)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write output files",
    )

    args = parser.parse_args()

    config = RunnerConfig(
        dry_run=args.dry_run,
        max_workers=args.max_workers,
        model=args.model,
        provider=args.provider,
    )

    work_numbers = args.work_numbers
    max_parallel = args.max_parallel

    print(f"\n{'='*60}")
    print(f"Parallel Translation Runner (DAG)")
    print(f"{'='*60}")
    print(f"Works: {', '.join(work_numbers)}")
    print(f"Max parallel: {max_parallel}")
    print(f"Model: {config.model or '(env default)'}")
    print(f"Provider: {config.provider or '(env default)'}")
    print(f"Resume: {args.resume}")
    print(f"{'='*60}\n")

    start_time = datetime.now()
    results = []

    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        futures = {
            executor.submit(
                translate_single_work,
                work_number=wn,
                config=config,
                resume=args.resume,
                volume=args.volume,
                from_node=args.from_node,
            ): wn
            for wn in work_numbers
        }

        for future in as_completed(futures):
            wn = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                logger.error(f"[{wn}] Failed with exception: {e}")
                results.append({
                    "work_number": wn,
                    "success": False,
                    "error": str(e),
                })

    end_time = datetime.now()
    total_duration = (end_time - start_time).total_seconds()

    # Print summary
    print(f"\n{'='*60}")
    print(f"PARALLEL TRANSLATION SUMMARY")
    print(f"{'='*60}")
    print(f"Total duration: {total_duration/60:.1f} minutes")
    print(f"Works processed: {len(results)}")

    successful = sum(1 for r in results if r.get("success", False))
    print(f"Successful: {successful}/{len(results)}")

    for result in sorted(results, key=lambda r: r.get("work_number", "")):
        wn = result.get("work_number", "?")
        status = "OK" if result.get("success") else "FAILED"
        duration = result.get("duration_seconds", 0)
        print(f"  {wn}: {status} ({duration/60:.1f} min)")
        if not result.get("success") and result.get("error"):
            print(f"    Error: {result['error']}")

    print(f"{'='*60}")

    # Save run report
    if not config.dry_run:
        report_path = config.log_dir / f"parallel_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump({
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_seconds": total_duration,
                "work_numbers": work_numbers,
                "results": results,
            }, f, ensure_ascii=False, indent=2)
        print(f"\nRun report: {report_path}")

    return 0 if successful == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
