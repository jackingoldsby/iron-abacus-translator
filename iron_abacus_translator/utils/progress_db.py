#!/usr/bin/env python3
"""
DuckDB-backed Progress Tracking

Append-only event store for pipeline progress at block/chapter/volume/work level.
Supports multi-level queries for status dashboards and auto-resume.

Usage:
    from utils.progress_db import ProgressDB, ProgressEvent

    db = ProgressDB()
    db.emit(ProgressEvent(
        run_id="run_20260325_120000",
        work_id="D60",
        stage="body",
        event_type="stage_start",
        status="running",
    ))

    status = db.get_latest_state("D60")
    print(status)  # {'last_completed_stage': 'headings', 'status': 'running'}
"""

import json
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default DB location
_DEFAULT_DB_DIR = Path.home() / "project_files" / "translation_project" / "db"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "pipeline_progress.duckdb"


@dataclass
class ProgressEvent:
    """A single progress event to record."""
    run_id: str
    work_id: str
    stage: str
    event_type: str  # stage_start, stage_end, chapter_start, chapter_end, block_done, error
    status: str = "running"  # running, completed, failed, skipped
    volume: Optional[str] = None
    chapter_num: Optional[int] = None
    block_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class StageProgress:
    """Progress summary for a single stage."""
    stage: str
    status: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_s: Optional[float] = None
    chapters_done: int = 0
    chapters_total: int = 0
    blocks_done: int = 0
    errors: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkProgress:
    """Progress summary for a whole work."""
    work_id: str
    run_id: Optional[str] = None
    stages: List[StageProgress] = field(default_factory=list)
    last_completed_stage: Optional[str] = None
    current_stage: Optional[str] = None
    status: str = "unknown"  # not_started, running, completed, failed
    total_events: int = 0


@dataclass
class ChapterProgress:
    """Progress summary for a chapter within a stage."""
    chapter_num: int
    stage: str
    status: str = "pending"
    blocks_done: int = 0
    blocks_total: int = 0
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_s: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ProgressDB:
    """DuckDB-backed progress tracking at block/chapter/volume/work level."""

    _CONNECT_TIMEOUT_S = 10

    def __init__(self, db_path: Optional[Path] = None, read_only: bool = False):
        try:
            import duckdb
        except ImportError:
            raise ImportError("duckdb is required: pip install duckdb")

        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.read_only = read_only

        if read_only:
            self._conn = self._connect_read_only(duckdb)
        else:
            self._conn = self._connect_with_recovery(duckdb)
        if not read_only:
            self._init_schema()

    def _connect_with_recovery(self, duckdb):
        """Connect with stale-lock recovery: detect dead PIDs, clean WAL, retry."""
        import signal
        import threading

        wal_path = Path(str(self.db_path) + ".wal")

        for attempt in range(2):
            result = [None]
            error = [None]

            def _try_connect():
                try:
                    result[0] = duckdb.connect(str(self.db_path))
                except Exception as e:
                    error[0] = e

            t = threading.Thread(target=_try_connect, daemon=True)
            t.start()
            t.join(timeout=self._CONNECT_TIMEOUT_S)

            if t.is_alive():
                # Connection hung — likely stale lock
                if attempt == 0 and wal_path.exists():
                    logger.warning(
                        f"DuckDB connect timed out after {self._CONNECT_TIMEOUT_S}s. "
                        f"Attempting stale lock recovery..."
                    )
                    if self._try_recover_stale_lock(wal_path):
                        continue  # retry after cleanup
                raise RuntimeError(
                    f"DuckDB connect timed out after {self._CONNECT_TIMEOUT_S}s. "
                    f"Database may be locked by another process. "
                    f"WAL exists: {wal_path.exists()}"
                )

            if error[0] is not None:
                err_str = str(error[0])
                if attempt == 0 and ("IO" in type(error[0]).__name__ or "lock" in err_str.lower()):
                    logger.warning(f"DuckDB lock error: {error[0]}")
                    if wal_path.exists() and self._try_recover_stale_lock(wal_path):
                        continue
                raise error[0]

            if result[0] is not None:
                logger.debug(f"DuckDB connected: {self.db_path}")
                return result[0]

        raise RuntimeError(f"Failed to connect to DuckDB after recovery attempts: {self.db_path}")

    def _try_recover_stale_lock(self, wal_path: Path) -> bool:
        """Check if locking PID is dead; if so, remove WAL and return True."""
        lock_path = Path(str(self.db_path) + ".lock")

        # Try to find the PID from the lock file
        locking_pid = None
        if lock_path.exists():
            try:
                content = lock_path.read_bytes()
                # DuckDB lock files sometimes contain the PID
                # Try to extract any integer that looks like a PID
                text = content.decode("utf-8", errors="ignore")
                nums = re.findall(r'\d+', text)
                for n in nums:
                    pid = int(n)
                    if 2 < pid < 2**22:  # reasonable PID range
                        locking_pid = pid
                        break
            except Exception:
                pass

        if locking_pid is not None:
            try:
                os.kill(locking_pid, 0)  # just check if alive
                raise RuntimeError(
                    f"Pipeline already running (PID {locking_pid}). "
                    f"If this is stale, kill PID {locking_pid} or remove {wal_path}"
                )
            except ProcessLookupError:
                logger.info(f"Locking PID {locking_pid} is dead — cleaning up stale WAL")
            except PermissionError:
                raise RuntimeError(
                    f"Pipeline locked by PID {locking_pid} (still running, different user). "
                    f"Cannot recover automatically."
                )
        else:
            # No PID found — WAL exists but no lock file or unreadable.
            # Check WAL age: if older than 1 hour, assume stale.
            try:
                age_s = (datetime.now() - datetime.fromtimestamp(wal_path.stat().st_mtime)).total_seconds()
                if age_s < 60:
                    raise RuntimeError(
                        f"DuckDB WAL file exists and is recent ({age_s:.0f}s old). "
                        f"Another pipeline may be running. Remove {wal_path} manually if stale."
                    )
                logger.info(f"Stale WAL detected ({age_s/60:.0f}min old, no lock PID) — cleaning up")
            except Exception as e:
                if "stale" not in str(e).lower() and "Pipeline" not in str(e):
                    logger.info(f"Cannot determine WAL age, attempting cleanup: {e}")

        # Remove stale WAL (and lock if present)
        try:
            wal_path.unlink(missing_ok=True)
            if lock_path.exists():
                lock_path.unlink(missing_ok=True)
            logger.info("Stale lock files removed — retrying connection")
            return True
        except OSError as e:
            logger.error(f"Failed to remove stale lock files: {e}")
            return False

    def _connect_read_only(self, duckdb):
        """Connect in read-only mode. Falls back to temp copy if WAL conflicts."""
        try:
            return duckdb.connect(str(self.db_path), read_only=True)
        except Exception:
            # WAL conflict — copy DB to temp file for reading
            if not self.db_path.exists():
                raise
            logger.debug("Read-only connect failed (WAL conflict), using temp copy")
            tmp = tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False)
            tmp.close()
            self._tmp_path = Path(tmp.name)
            shutil.copy2(self.db_path, self._tmp_path)
            return duckdb.connect(str(self._tmp_path), read_only=True)

    def _init_schema(self):
        """Create the events table if it doesn't exist."""
        self._conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS pipeline_events_id_seq;
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_events (
                id              INTEGER DEFAULT nextval('pipeline_events_id_seq') PRIMARY KEY,
                run_id          VARCHAR,
                work_id         VARCHAR NOT NULL,
                volume          VARCHAR,
                stage           VARCHAR NOT NULL,
                chapter_num     INTEGER,
                block_id        VARCHAR,
                event_type      VARCHAR NOT NULL,
                status          VARCHAR,
                metadata        JSON,
                created_at      TIMESTAMP DEFAULT current_timestamp
            );
        """)
        # Index for common queries
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_work_id
            ON pipeline_events (work_id, stage, event_type);
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_run_id
            ON pipeline_events (run_id);
        """)

    def emit(self, event: ProgressEvent):
        """Append a progress event."""
        if self.read_only:
            raise RuntimeError("Cannot emit events on a read-only ProgressDB")
        meta_json = json.dumps(event.metadata) if event.metadata else None
        self._conn.execute("""
            INSERT INTO pipeline_events
                (run_id, work_id, volume, stage, chapter_num, block_id,
                 event_type, status, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            event.run_id, event.work_id, event.volume, event.stage,
            event.chapter_num, event.block_id,
            event.event_type, event.status, meta_json,
        ])

    def query_work(self, work_id: str, run_id: Optional[str] = None) -> WorkProgress:
        """Aggregate work-level progress from events."""
        # Find the latest run_id if not specified
        if run_id is None:
            row = self._conn.execute("""
                SELECT run_id FROM pipeline_events
                WHERE work_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, [work_id]).fetchone()
            if not row:
                return WorkProgress(work_id=work_id, status="not_started")
            run_id = row[0]

        # Count total events
        total = self._conn.execute("""
            SELECT COUNT(*) FROM pipeline_events
            WHERE work_id = ? AND run_id = ?
        """, [work_id, run_id]).fetchone()[0]

        # Get stage-level summary
        stage_rows = self._conn.execute("""
            SELECT
                stage,
                MIN(CASE WHEN event_type = 'stage_start' THEN created_at END) as started_at,
                MAX(CASE WHEN event_type = 'stage_end' THEN created_at END) as ended_at,
                MAX(CASE WHEN event_type = 'stage_end' THEN status END) as final_status,
                COUNT(CASE WHEN event_type = 'chapter_end' THEN 1 END) as chapters_done,
                COUNT(CASE WHEN event_type = 'block_done' THEN 1 END) as blocks_done,
                COUNT(CASE WHEN event_type = 'error' THEN 1 END) as errors
            FROM pipeline_events
            WHERE work_id = ? AND run_id = ?
            GROUP BY stage
            ORDER BY MIN(created_at)
        """, [work_id, run_id]).fetchall()

        stages = []
        last_completed = None
        current_stage = None

        for row in stage_rows:
            stage_name, started, ended, final_status, ch_done, bl_done, errs = row
            status = final_status or "running"
            duration = None
            if started and ended:
                duration = (ended - started).total_seconds()

            stages.append(StageProgress(
                stage=stage_name,
                status=status,
                started_at=started.isoformat() if started else None,
                ended_at=ended.isoformat() if ended else None,
                duration_s=round(duration, 2) if duration else None,
                chapters_done=ch_done,
                blocks_done=bl_done,
                errors=errs,
            ))

            if status == "completed":
                last_completed = stage_name
            elif status == "running":
                current_stage = stage_name

        # Determine overall status
        if not stages:
            overall = "not_started"
        elif any(s.status == "failed" for s in stages):
            overall = "failed"
        elif current_stage:
            overall = "running"
        elif all(s.status in ("completed", "skipped") for s in stages):
            overall = "completed"
        else:
            overall = "running"

        return WorkProgress(
            work_id=work_id,
            run_id=run_id,
            stages=stages,
            last_completed_stage=last_completed,
            current_stage=current_stage,
            status=overall,
            total_events=total,
        )

    def query_stage(self, work_id: str, stage: str,
                    run_id: Optional[str] = None) -> StageProgress:
        """Per-chapter breakdown within a stage."""
        if run_id is None:
            row = self._conn.execute("""
                SELECT run_id FROM pipeline_events
                WHERE work_id = ? AND stage = ?
                ORDER BY created_at DESC LIMIT 1
            """, [work_id, stage]).fetchone()
            if not row:
                return StageProgress(stage=stage, status="not_started")
            run_id = row[0]

        row = self._conn.execute("""
            SELECT
                MIN(CASE WHEN event_type = 'stage_start' THEN created_at END),
                MAX(CASE WHEN event_type = 'stage_end' THEN created_at END),
                MAX(CASE WHEN event_type = 'stage_end' THEN status END),
                COUNT(CASE WHEN event_type = 'chapter_end' THEN 1 END),
                COUNT(CASE WHEN event_type = 'chapter_start' THEN 1 END),
                COUNT(CASE WHEN event_type = 'block_done' THEN 1 END),
                COUNT(CASE WHEN event_type = 'error' THEN 1 END)
            FROM pipeline_events
            WHERE work_id = ? AND run_id = ? AND stage = ?
        """, [work_id, run_id, stage]).fetchone()

        started, ended, final_status, ch_done, ch_total, bl_done, errs = row
        status = final_status or ("running" if started else "not_started")
        duration = None
        if started and ended:
            duration = (ended - started).total_seconds()

        return StageProgress(
            stage=stage,
            status=status,
            started_at=started.isoformat() if started else None,
            ended_at=ended.isoformat() if ended else None,
            duration_s=round(duration, 2) if duration else None,
            chapters_done=ch_done,
            chapters_total=ch_total,
            blocks_done=bl_done,
            errors=errs,
        )

    def query_chapters(self, work_id: str, stage: str,
                       run_id: Optional[str] = None) -> List[ChapterProgress]:
        """Per-chapter breakdown within a stage."""
        if run_id is None:
            row = self._conn.execute("""
                SELECT run_id FROM pipeline_events
                WHERE work_id = ? AND stage = ?
                ORDER BY created_at DESC LIMIT 1
            """, [work_id, stage]).fetchone()
            if not row:
                return []
            run_id = row[0]

        rows = self._conn.execute("""
            SELECT
                chapter_num,
                MIN(CASE WHEN event_type = 'chapter_start' THEN created_at END) as started,
                MAX(CASE WHEN event_type = 'chapter_end' THEN created_at END) as ended,
                MAX(CASE WHEN event_type = 'chapter_end' THEN status END) as status,
                COUNT(CASE WHEN event_type = 'block_done' THEN 1 END) as blocks_done
            FROM pipeline_events
            WHERE work_id = ? AND run_id = ? AND stage = ?
                  AND chapter_num IS NOT NULL
            GROUP BY chapter_num
            ORDER BY chapter_num
        """, [work_id, run_id, stage]).fetchall()

        results = []
        for row in rows:
            ch_num, started, ended, status, bl_done = row
            status = status or ("running" if started else "pending")
            duration = None
            if started and ended:
                duration = (ended - started).total_seconds()
            results.append(ChapterProgress(
                chapter_num=ch_num,
                stage=stage,
                status=status,
                blocks_done=bl_done,
                started_at=started.isoformat() if started else None,
                ended_at=ended.isoformat() if ended else None,
                duration_s=round(duration, 2) if duration else None,
            ))
        return results

    def get_latest_state(self, work_id: str) -> Dict[str, Any]:
        """What's the last completed stage? Used for auto-resume."""
        row = self._conn.execute("""
            SELECT run_id, stage, status, created_at
            FROM pipeline_events
            WHERE work_id = ? AND event_type = 'stage_end' AND status = 'completed'
            ORDER BY created_at DESC
            LIMIT 1
        """, [work_id]).fetchone()

        if not row:
            return {
                "work_id": work_id,
                "last_completed_stage": None,
                "status": "not_started",
            }

        return {
            "work_id": work_id,
            "last_completed_stage": row[1],
            "run_id": row[0],
            "completed_at": row[3].isoformat() if row[3] else None,
            "status": "resumable",
        }

    def get_run_ids(self, work_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """List recent run IDs for a work."""
        rows = self._conn.execute("""
            SELECT
                run_id,
                MIN(created_at) as started,
                MAX(created_at) as last_event,
                COUNT(*) as event_count
            FROM pipeline_events
            WHERE work_id = ?
            GROUP BY run_id
            ORDER BY MIN(created_at) DESC
            LIMIT ?
        """, [work_id, limit]).fetchall()

        return [
            {
                "run_id": r[0],
                "started_at": r[1].isoformat() if r[1] else None,
                "last_event_at": r[2].isoformat() if r[2] else None,
                "event_count": r[3],
            }
            for r in rows
        ]

    def close(self):
        """Close the database connection."""
        self._conn.close()
        # Clean up temp copy if we made one for read-only mode
        tmp = getattr(self, '_tmp_path', None)
        if tmp and tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
