#!/usr/bin/env python3
"""
Library Path Resolver

Resolves work numbers to human-readable library paths using the DuckDB catalog.

Layout: library/{Author}/{Series}/{NN_Title}/[vol_X/]{raw,cleaned,translation,epub}

Usage:
    from utils.library_path_resolver import resolve_work_path, sanitize_dirname

    path = resolve_work_path("D438", catalog_path)
    # -> PurePosixPath("Liang_Yusheng/Tianshan_Series/01_The_White-Haired_Demoness")
"""

import re
import logging
from pathlib import Path, PurePosixPath
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Chars unsafe in directory names on any OS
_UNSAFE_CHARS = r':/\?*"<>|'

# Fullwidth punctuation to strip or replace
_FULLWIDTH_MAP = {
    '\uff0e': '_',   # fullwidth period → underscore
    '\uff0c': '',    # fullwidth comma → remove
    '\u3002': '',    # ideographic period → remove
    '\uff1a': '',    # fullwidth colon → remove
    '\uff1b': '',    # fullwidth semicolon → remove
    '\uff01': '',    # fullwidth exclamation → remove
    '\uff1f': '',    # fullwidth question → remove
    '\u3001': '',    # ideographic comma → remove
    '\u300a': '',    # left double angle bracket → remove
    '\u300b': '',    # right double angle bracket → remove
    '\uff08': '_',   # fullwidth left paren → underscore
    '\uff09': '_',   # fullwidth right paren → underscore
    '\u2014': '-',   # em-dash → hyphen
    '\u2013': '-',   # en-dash → hyphen
    '\uff0d': '-',   # fullwidth hyphen → hyphen
}


def sanitize_dirname(name: str) -> str:
    """
    Make a filesystem-safe directory name.

    - Strips unsafe ASCII chars (:/\\?*"<>|)
    - Replaces fullwidth punctuation
    - Spaces → underscores
    - Collapses runs of underscores
    - Strips leading/trailing underscores and hyphens
    """
    if not name:
        return "_unknown"

    # Replace fullwidth punctuation
    for char, replacement in _FULLWIDTH_MAP.items():
        name = name.replace(char, replacement)

    # Remove unsafe ASCII chars
    for ch in _UNSAFE_CHARS:
        name = name.replace(ch, '')

    # Periods at start (hidden files on Unix)
    name = name.lstrip('.')

    # Spaces to underscores
    name = name.replace(' ', '_')

    # Collapse multiple underscores/hyphens
    name = re.sub(r'_+', '_', name)
    name = re.sub(r'-+', '-', name)

    # Strip leading/trailing underscores and hyphens
    name = name.strip('_').strip('-').strip('_')

    return name or "_unknown"


@dataclass
class WorkLibraryInfo:
    """Resolved library info for a work."""
    work_number: str
    title_english: str
    author_english: str
    series_name: Optional[str]
    order_in_series: Optional[int]
    volumes: List[str]  # list of volume letters (empty if single-volume)
    relative_path: str  # e.g. "Liang_Yusheng/Tianshan_Series/01_The_White-Haired_Demoness"


def _query_work_info(work_number: str, catalog_path: Path) -> Optional[Dict[str, Any]]:
    """Query catalog for work metadata including series info."""
    import duckdb

    conn = duckdb.connect(str(catalog_path), read_only=True)
    try:
        row = conn.execute("""
            SELECT
                w.work_id,
                w.work_number,
                w.title_english,
                w.author_english,
                s.name_english AS series_name,
                ws.order_in_series
            FROM works w
            LEFT JOIN work_series ws ON w.work_id = ws.work_id
            LEFT JOIN series s ON ws.series_id = s.series_id
            WHERE w.work_number = ?
        """, [work_number]).fetchone()

        if not row:
            return None

        # Get volumes
        volumes = conn.execute("""
            SELECT DISTINCT volume
            FROM work_files
            WHERE work_id = ?
            AND volume IS NOT NULL AND volume != ''
            ORDER BY volume
        """, [row[0]]).fetchall()

        return {
            "work_id": row[0],
            "work_number": row[1],
            "title_english": row[2] or work_number,
            "author_english": row[3] or "Unknown_Author",
            "series_name": row[4],
            "order_in_series": row[5],
            "volumes": [v[0] for v in volumes],
        }
    finally:
        conn.close()


def resolve_work_path(work_number: str, catalog_path: Path) -> Optional[str]:
    """
    Resolve a work number to a relative library path.

    Returns a string like:
        "Liang_Yusheng/Tianshan_Series/01_The_White-Haired_Demoness"

    Args:
        work_number: e.g. "D438", "FSYY"
        catalog_path: Path to works_translator.duckdb

    Returns:
        Relative path string from library/, or None if work not found.
    """
    info = resolve_work_info(work_number, catalog_path)
    if not info:
        return None
    return info.relative_path


def resolve_work_info(work_number: str, catalog_path: Path) -> Optional[WorkLibraryInfo]:
    """
    Resolve full library info for a work.

    Returns WorkLibraryInfo with relative_path and metadata.
    """
    data = _query_work_info(work_number, catalog_path)
    if not data:
        logger.warning(f"Work {work_number} not found in catalog")
        return None

    author_dir = sanitize_dirname(data["author_english"])
    title_dir = sanitize_dirname(data["title_english"])

    if data["series_name"]:
        series_dir = sanitize_dirname(data["series_name"])
        order = data["order_in_series"]
        if order is not None:
            work_dir = f"{order:02d}_{title_dir}"
        else:
            work_dir = title_dir
        relative_path = f"{author_dir}/{series_dir}/{work_dir}"
    else:
        relative_path = f"{author_dir}/_standalone/{title_dir}"

    return WorkLibraryInfo(
        work_number=data["work_number"],
        title_english=data["title_english"],
        author_english=data["author_english"],
        series_name=data["series_name"],
        order_in_series=data["order_in_series"],
        volumes=data["volumes"],
        relative_path=relative_path,
    )


def resolve_volume_path(
    work_number: str, volume: str, catalog_path: Path
) -> Optional[str]:
    """
    Resolve a work+volume to a relative library path including the vol_X dir.

    Returns e.g.: "Jin_Yong/Condor_Trilogy/01_Legend_of_the_Condor_Heroes/vol_a"
    """
    info = resolve_work_info(work_number, catalog_path)
    if not info:
        return None

    vol_letter = volume.lower().strip()
    return f"{info.relative_path}/vol_{vol_letter}"


def get_work_dir(
    work_number: str,
    library_root: Path,
    catalog_path: Path,
    volume: Optional[str] = None,
) -> Optional[Path]:
    """
    Get the absolute work directory path.

    For multi-volume works with a volume specified, returns the vol_X subdir.
    For single-volume works, returns the work dir directly.
    """
    info = resolve_work_info(work_number, catalog_path)
    if not info:
        return None

    work_path = library_root / info.relative_path

    if volume:
        return work_path / f"vol_{volume.lower().strip()}"
    elif info.volumes:
        # Multi-volume work but no volume specified — return work-level dir
        return work_path
    else:
        return work_path


def create_work_skeleton(
    work_number: str,
    library_root: Path,
    catalog_path: Path,
    dry_run: bool = False,
) -> Optional[Path]:
    """
    Create the directory skeleton for a work.

    For single-volume: raw/, cleaned/, translation/, epub/
    For multi-volume: vol_a/{raw,cleaned,translation}/, ..., epub/

    Returns the work directory path.
    """
    info = resolve_work_info(work_number, catalog_path)
    if not info:
        return None

    work_path = library_root / info.relative_path

    if info.volumes:
        # Multi-volume: per-volume subdirs + work-level epub
        for vol in info.volumes:
            for subdir in ["raw", "cleaned", "translation", "translation/wip"]:
                d = work_path / f"vol_{vol}" / subdir
                if dry_run:
                    logger.info(f"  Would create: {d}")
                else:
                    d.mkdir(parents=True, exist_ok=True)
        # Work-level epub dir
        epub_dir = work_path / "epub"
        if dry_run:
            logger.info(f"  Would create: {epub_dir}")
        else:
            epub_dir.mkdir(parents=True, exist_ok=True)
    else:
        # Single-volume: flat structure
        for subdir in ["raw", "cleaned", "translation", "translation/wip", "epub"]:
            d = work_path / subdir
            if dry_run:
                logger.info(f"  Would create: {d}")
            else:
                d.mkdir(parents=True, exist_ok=True)

    return work_path


def build_status_json(
    work_number: str,
    catalog_path: Path,
    stages_completed: Optional[List[int]] = None,
    epub_generated: bool = False,
) -> Optional[Dict[str, Any]]:
    """Build a status.json dict for a work."""
    info = resolve_work_info(work_number, catalog_path)
    if not info:
        return None

    return {
        "work_id": work_number,
        "work_number": work_number,
        "title_english": info.title_english,
        "author_english": info.author_english,
        "series": info.series_name,
        "order_in_series": info.order_in_series,
        "volumes": info.volumes if info.volumes else None,
        "stages_completed": stages_completed or [],
        "last_run": None,
        "footnotes_final": None,
        "epub_generated": epub_generated,
        "library_path": info.relative_path,
    }


# ─── CLI ────────────────────────────────────────────────────────────────────

def main():
    """CLI for testing path resolution."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python utils/library_path_resolver.py <work_number> [catalog_path]")
        print("       python utils/library_path_resolver.py --all [catalog_path]")
        return 1

    from utils.environment_config import get_or_create_config
    config = get_or_create_config()

    catalog_path = Path(sys.argv[2]) if len(sys.argv) > 2 else config.catalog_path

    if sys.argv[1] == "--all":
        # Resolve all works
        import duckdb
        conn = duckdb.connect(str(catalog_path), read_only=True)
        work_numbers = [r[0] for r in conn.execute(
            "SELECT work_number FROM works ORDER BY work_number"
        ).fetchall()]
        conn.close()

        resolved = 0
        failed = 0
        for wn in work_numbers:
            info = resolve_work_info(wn, catalog_path)
            if info:
                vols = f" (vols: {','.join(info.volumes)})" if info.volumes else ""
                print(f"  {wn}: library/{info.relative_path}/{vols}")
                resolved += 1
            else:
                print(f"  {wn}: FAILED TO RESOLVE")
                failed += 1

        print(f"\nResolved: {resolved}/{len(work_numbers)}, Failed: {failed}")
        return 0 if failed == 0 else 1

    # Single work
    work_number = sys.argv[1]
    info = resolve_work_info(work_number, catalog_path)
    if info:
        print(f"Work:    {info.work_number}")
        print(f"Title:   {info.title_english}")
        print(f"Author:  {info.author_english}")
        print(f"Series:  {info.series_name or '(standalone)'}")
        if info.order_in_series:
            print(f"Order:   #{info.order_in_series}")
        if info.volumes:
            print(f"Volumes: {', '.join(info.volumes)}")
        print(f"Path:    library/{info.relative_path}/")
        return 0
    else:
        print(f"Work {work_number} not found in catalog")
        return 1


if __name__ == "__main__":
    exit(main())
