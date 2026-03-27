#!/usr/bin/env python3
"""
Progress Query API

REST endpoints for querying pipeline progress from DuckDB.
Integrates with the existing FastAPI backend.

Endpoints:
    GET /api/pipeline/{work_id}/status      - Work-level summary
    GET /api/pipeline/{work_id}/stages      - Per-stage breakdown
    GET /api/pipeline/{work_id}/chapters    - Per-chapter breakdown for a stage
    GET /api/pipeline/{work_id}/runs        - List recent runs
    POST /api/pipeline/start                - Start a pipeline run
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.progress_db import ProgressDB

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------

class StageStatusResponse(BaseModel):
    stage: str
    status: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_s: Optional[float] = None
    chapters_done: int = 0
    chapters_total: int = 0
    blocks_done: int = 0
    errors: int = 0


class WorkStatusResponse(BaseModel):
    work_id: str
    run_id: Optional[str] = None
    status: str
    last_completed_stage: Optional[str] = None
    current_stage: Optional[str] = None
    total_events: int = 0
    stages: List[StageStatusResponse] = []


class ChapterStatusResponse(BaseModel):
    chapter_num: int
    stage: str
    status: str = "pending"
    blocks_done: int = 0
    blocks_total: int = 0
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_s: Optional[float] = None


class RunInfoResponse(BaseModel):
    run_id: str
    started_at: Optional[str] = None
    last_event_at: Optional[str] = None
    event_count: int = 0


class PipelineStartRequest(BaseModel):
    work_id: str
    volume: Optional[str] = None
    from_node: Optional[str] = None
    resume: bool = False
    provider: Optional[str] = None
    model: Optional[str] = None
    workers: int = 5
    chapters: int = 0


class PipelineStartResponse(BaseModel):
    success: bool
    message: str
    run_id: Optional[str] = None


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------

def _get_db(read_only: bool = False) -> ProgressDB:
    """Get a ProgressDB instance."""
    return ProgressDB(read_only=read_only)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/{work_id}/status", response_model=WorkStatusResponse)
async def get_work_status(work_id: str, run_id: Optional[str] = None):
    """Get work-level progress summary."""
    db = _get_db(read_only=True)
    try:
        progress = db.query_work(work_id, run_id=run_id)
        return WorkStatusResponse(
            work_id=progress.work_id,
            run_id=progress.run_id,
            status=progress.status,
            last_completed_stage=progress.last_completed_stage,
            current_stage=progress.current_stage,
            total_events=progress.total_events,
            stages=[
                StageStatusResponse(
                    stage=s.stage,
                    status=s.status,
                    started_at=s.started_at,
                    ended_at=s.ended_at,
                    duration_s=s.duration_s,
                    chapters_done=s.chapters_done,
                    chapters_total=s.chapters_total,
                    blocks_done=s.blocks_done,
                    errors=s.errors,
                )
                for s in progress.stages
            ],
        )
    finally:
        db.close()


@router.get("/{work_id}/stages", response_model=List[StageStatusResponse])
async def get_stages(work_id: str, run_id: Optional[str] = None):
    """Get per-stage breakdown."""
    db = _get_db(read_only=True)
    try:
        progress = db.query_work(work_id, run_id=run_id)
        if progress.status == "not_started":
            raise HTTPException(status_code=404, detail=f"No runs found for {work_id}")
        return [
            StageStatusResponse(
                stage=s.stage,
                status=s.status,
                started_at=s.started_at,
                ended_at=s.ended_at,
                duration_s=s.duration_s,
                chapters_done=s.chapters_done,
                chapters_total=s.chapters_total,
                blocks_done=s.blocks_done,
                errors=s.errors,
            )
            for s in progress.stages
        ]
    finally:
        db.close()


@router.get("/{work_id}/chapters", response_model=List[ChapterStatusResponse])
async def get_chapters(
    work_id: str,
    stage: str = Query(..., description="Stage name (e.g. body, cleanup_6a)"),
    run_id: Optional[str] = None,
):
    """Get per-chapter breakdown within a stage."""
    db = _get_db(read_only=True)
    try:
        chapters = db.query_chapters(work_id, stage, run_id=run_id)
        if not chapters:
            raise HTTPException(
                status_code=404,
                detail=f"No chapter data for {work_id}/{stage}",
            )
        return [
            ChapterStatusResponse(
                chapter_num=ch.chapter_num,
                stage=ch.stage,
                status=ch.status,
                blocks_done=ch.blocks_done,
                blocks_total=ch.blocks_total,
                started_at=ch.started_at,
                ended_at=ch.ended_at,
                duration_s=ch.duration_s,
            )
            for ch in chapters
        ]
    finally:
        db.close()


@router.get("/{work_id}/runs", response_model=List[RunInfoResponse])
async def get_runs(work_id: str, limit: int = 10):
    """List recent pipeline runs for a work."""
    db = _get_db(read_only=True)
    try:
        runs = db.get_run_ids(work_id, limit=limit)
        return [
            RunInfoResponse(**r)
            for r in runs
        ]
    finally:
        db.close()


@router.post("/start", response_model=PipelineStartResponse)
async def start_pipeline(request: PipelineStartRequest):
    """Start a pipeline run in the background."""
    from scripts.pipeline_runner import RunnerConfig, build_pipeline

    # Resolve model
    model = request.model
    if request.provider and not model:
        provider_models = {
            "deepseek": "deepseek-chat",
            "openai": "gpt-4.1-nano",
        }
        model = provider_models.get(request.provider, request.provider)

    config = RunnerConfig(
        model=model,
        provider=request.provider,
        max_workers=request.workers,
    )

    db = ProgressDB()

    runner = build_pipeline(config, db)

    # Run in background thread
    async def _run():
        try:
            result = await asyncio.to_thread(
                runner.run,
                work_id=request.work_id,
                volume=request.volume,
                from_node=request.from_node,
                resume=request.resume,
                chapter_limit=request.chapters,
            )
            logger.info(f"Pipeline {request.work_id} finished: success={result['success']}")
        except Exception as e:
            logger.error(f"Pipeline {request.work_id} failed: {e}")
        finally:
            db.close()

    asyncio.create_task(_run())

    return PipelineStartResponse(
        success=True,
        message=f"Pipeline started for {request.work_id}",
    )
