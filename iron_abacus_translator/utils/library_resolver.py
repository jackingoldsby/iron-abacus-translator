#!/usr/bin/env python3
"""
Library Resolver — Resolve series, works, and volumes from library status.json files.

Usage:
    from utils.library_resolver import resolve_series, resolve_work, list_series

    works = resolve_series("Condor Trilogy")
    work = resolve_work("D57")
    all_series = list_series()
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Default library root
_DEFAULT_LIBRARY_ROOT = Path.home() / "project_files" / "translation_project" / "library"


@dataclass
class WorkInfo:
    """Metadata for a single work resolved from library status.json."""
    work_id: str
    title_english: str = ""
    author_english: str = ""
    series: Optional[str] = None
    order_in_series: Optional[int] = None
    volumes: Optional[List[str]] = None
    library_path: str = ""
    status_path: Optional[Path] = None

    @property
    def is_multi_volume(self) -> bool:
        return bool(self.volumes and len(self.volumes) > 1)


def _get_library_root() -> Path:
    """Get library root, checking env var first."""
    import os
    root = os.environ.get("TRANSLATOR_LIBRARY_ROOT")
    if root:
        return Path(root)
    return _DEFAULT_LIBRARY_ROOT


def _scan_status_files(library_root: Path = None) -> List[dict]:
    """Scan all status.json files in the library."""
    if library_root is None:
        library_root = _get_library_root()

    results = []
    for status_path in library_root.rglob("status.json"):
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["_status_path"] = str(status_path)
            results.append(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read {status_path}: {e}")
    return results


def resolve_work(work_id: str, library_root: Path = None) -> Optional[WorkInfo]:
    """Resolve a single work by ID from library status.json files."""
    for entry in _scan_status_files(library_root):
        if entry.get("work_id") == work_id or entry.get("work_number") == work_id:
            return WorkInfo(
                work_id=entry.get("work_id", work_id),
                title_english=entry.get("title_english", ""),
                author_english=entry.get("author_english", ""),
                series=entry.get("series"),
                order_in_series=entry.get("order_in_series"),
                volumes=entry.get("volumes"),
                library_path=entry.get("library_path", ""),
                status_path=Path(entry["_status_path"]),
            )
    return None


def resolve_series(name_or_path: str, library_root: Path = None) -> List[WorkInfo]:
    """
    Resolve all works in a series, sorted by order_in_series.

    Args:
        name_or_path: Series name ("Condor Trilogy"), path ("Jin_Yong/Condor_Trilogy"),
                      or partial match.
        library_root: Override library root path.

    Returns:
        List of WorkInfo sorted by order_in_series.
    """
    if library_root is None:
        library_root = _get_library_root()

    all_entries = _scan_status_files(library_root)
    name_lower = name_or_path.lower().replace("_", " ")

    matches = []
    for entry in all_entries:
        series = entry.get("series")
        lib_path = entry.get("library_path", "")

        matched = False
        # Match by series name (exact or case-insensitive)
        if series and series.lower() == name_lower:
            matched = True
        # Match by library path containing the series path
        elif lib_path and name_or_path.replace(" ", "_") in lib_path:
            matched = True
        # Match by directory name in library path
        elif lib_path:
            parts = lib_path.split("/")
            for part in parts:
                if part.lower().replace("_", " ") == name_lower:
                    matched = True
                    break

        if matched:
            matches.append(WorkInfo(
                work_id=entry.get("work_id", ""),
                title_english=entry.get("title_english", ""),
                author_english=entry.get("author_english", ""),
                series=series,
                order_in_series=entry.get("order_in_series"),
                volumes=entry.get("volumes"),
                library_path=lib_path,
                status_path=Path(entry["_status_path"]),
            ))

    # Sort by order_in_series (None sorts last)
    matches.sort(key=lambda w: (w.order_in_series or 999, w.work_id))

    if not matches:
        logger.warning(f"No works found for series '{name_or_path}'")
    else:
        logger.info(
            f"Resolved series '{name_or_path}': {len(matches)} works — "
            + ", ".join(f"{w.work_id} ({w.title_english})" for w in matches)
        )

    return matches


def list_series(library_root: Path = None) -> dict:
    """
    List all series in the library.

    Returns:
        Dict mapping series name to list of WorkInfo.
    """
    all_entries = _scan_status_files(library_root)
    series_map = {}

    for entry in all_entries:
        series = entry.get("series")
        if not series:
            continue
        if series not in series_map:
            series_map[series] = []
        series_map[series].append(WorkInfo(
            work_id=entry.get("work_id", ""),
            title_english=entry.get("title_english", ""),
            author_english=entry.get("author_english", ""),
            series=series,
            order_in_series=entry.get("order_in_series"),
            volumes=entry.get("volumes"),
            library_path=entry.get("library_path", ""),
            status_path=Path(entry["_status_path"]),
        ))

    # Sort within each series
    for name in series_map:
        series_map[name].sort(key=lambda w: (w.order_in_series or 999, w.work_id))

    return series_map


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        works = resolve_series(query)
        if works:
            for w in works:
                vols = f" volumes={w.volumes}" if w.volumes else ""
                print(f"  {w.order_in_series or '?'}. {w.work_id} — {w.title_english} by {w.author_english}{vols}")
        else:
            # Try as work ID
            work = resolve_work(query)
            if work:
                print(f"  {work.work_id} — {work.title_english} by {work.author_english}")
                if work.series:
                    print(f"  Series: {work.series} (#{work.order_in_series})")
                if work.volumes:
                    print(f"  Volumes: {', '.join(work.volumes)}")
    else:
        print("All series in library:\n")
        series = list_series()
        for name, works in sorted(series.items()):
            print(f"  {name} ({len(works)} works):")
            for w in works:
                print(f"    {w.order_in_series or '?'}. {w.work_id} — {w.title_english}")
        print(f"\n  Total: {len(series)} series")
