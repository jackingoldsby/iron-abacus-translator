#!/usr/bin/env python3
"""
DAG Pipeline API Endpoints

REST API + SSE for DAG-based pipeline visualization and execution:
- Get pipeline DAG definitions (V1/V2)
- Start/monitor/control DAG runs
- Real-time SSE streaming of node status updates
- Multi-volume batch run support
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from workflows.dag_engine import DAGDefinition, NodeStatus
from workflows.translation_pipeline_dag import create_v2_pipeline_dag, create_v1_pipeline_dag

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dag", tags=["dag"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class DAGRunCreate(BaseModel):
    """Request to start a new DAG run."""
    work_id: str
    volumes: List[str] = Field(default_factory=list)
    pipeline_version: str = "v2"
    config: Dict[str, Any] = Field(default_factory=dict)


class DAGNodeAction(BaseModel):
    """Request to act on a specific node."""
    reason: Optional[str] = None


class DAGRunSummary(BaseModel):
    """Summary of a DAG run."""
    run_id: str
    work_id: str
    volumes: List[str]
    pipeline_version: str
    status: str
    overall_progress_pct: float
    created_at: str
    updated_at: str
    current_node: Optional[str] = None
    batch_id: Optional[str] = None


# =============================================================================
# IN-MEMORY STATE (production would use a DB)
# =============================================================================

dag_runs: Dict[str, Dict[str, Any]] = {}
dag_run_events: Dict[str, asyncio.Queue] = {}


def _create_run_state(run_id: str, work_id: str, volumes: List[str],
                      pipeline_version: str, dag: DAGDefinition,
                      batch_id: Optional[str] = None) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "run_id": run_id,
        "work_id": work_id,
        "volumes": volumes,
        "pipeline_version": pipeline_version,
        "status": "pending",
        "overall_progress_pct": 0.0,
        "created_at": now,
        "updated_at": now,
        "current_node": None,
        "batch_id": batch_id,
        "dag": dag.to_dict(),
        "node_statuses": {nid: {"status": "pending", "progress_pct": 0.0} for nid in dag.nodes},
        "node_logs": {},
        "node_timings": {},
    }


def _compute_progress(run_state: Dict[str, Any]) -> float:
    statuses = run_state["node_statuses"]
    if not statuses:
        return 0.0
    completed = sum(1 for s in statuses.values() if s["status"] in ("completed", "skipped"))
    return round((completed / len(statuses)) * 100, 1)


async def _emit_event(run_id: str, event: Dict[str, Any]):
    if run_id in dag_run_events:
        await dag_run_events[run_id].put(event)


# =============================================================================
# PIPELINE DEFINITION ENDPOINTS
# =============================================================================

@router.get("/pipeline")
async def get_v2_pipeline():
    """Get the V2 translation pipeline DAG definition."""
    dag = create_v2_pipeline_dag()
    return dag.to_dict()


@router.get("/pipeline/v1")
async def get_v1_pipeline():
    """Get the V1 (linear) translation pipeline DAG definition."""
    dag = create_v1_pipeline_dag()
    return dag.to_dict()


# =============================================================================
# RUN MANAGEMENT ENDPOINTS
# =============================================================================

@router.post("/run")
async def start_dag_run(request: DAGRunCreate):
    """
    Start a new DAG run.

    For multi-volume works, creates one DAG run per volume linked by a batch ID.
    Returns the run ID (or batch ID for multi-volume).
    """
    pipeline_version = request.pipeline_version
    dag_factory = create_v2_pipeline_dag if pipeline_version == "v2" else create_v1_pipeline_dag

    volumes = request.volumes if request.volumes else ["single"]

    if len(volumes) > 1:
        batch_id = f"batch_{uuid.uuid4().hex[:12]}"
        runs = []

        for vol in volumes:
            run_id = f"run_{uuid.uuid4().hex[:12]}"
            dag = dag_factory()
            run_state = _create_run_state(run_id, request.work_id, [vol],
                                          pipeline_version, dag, batch_id)
            dag_runs[run_id] = run_state
            dag_run_events[run_id] = asyncio.Queue()
            runs.append({"run_id": run_id, "volume": vol})

        return {
            "batch_id": batch_id,
            "work_id": request.work_id,
            "runs": runs,
            "total_volumes": len(volumes),
        }
    else:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        dag = dag_factory()
        run_state = _create_run_state(run_id, request.work_id, volumes,
                                      pipeline_version, dag)
        dag_runs[run_id] = run_state
        dag_run_events[run_id] = asyncio.Queue()

        return {
            "run_id": run_id,
            "work_id": request.work_id,
            "volumes": volumes,
        }


@router.get("/run/{run_id}")
async def get_dag_run(run_id: str):
    """Get full DAG run status including all node states."""
    if run_id not in dag_runs:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    run = dag_runs[run_id]
    run["overall_progress_pct"] = _compute_progress(run)
    return run


@router.get("/run/{run_id}/stream")
async def stream_dag_run(run_id: str, request: Request):
    """SSE stream for real-time node status updates."""
    if run_id not in dag_runs:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    if run_id not in dag_run_events:
        dag_run_events[run_id] = asyncio.Queue()

    async def event_generator():
        queue = dag_run_events[run_id]

        # Send initial state
        run = dag_runs[run_id]
        run["overall_progress_pct"] = _compute_progress(run)
        yield f"data: {json.dumps({'type': 'initial', 'run': run})}\n\n"

        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/run/{run_id}/validate/{node_id}")
async def validate_node(run_id: str, node_id: str, action: DAGNodeAction = None):
    """Manually mark a quality gate node as validated (passed)."""
    if run_id not in dag_runs:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    run = dag_runs[run_id]
    if node_id not in run["node_statuses"]:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")

    run["node_statuses"][node_id] = {"status": "completed", "progress_pct": 100.0}
    run["updated_at"] = datetime.now(timezone.utc).isoformat()

    await _emit_event(run_id, {
        "type": "node_update",
        "node_id": node_id,
        "status": "completed",
        "progress_pct": 100.0,
    })

    return {"node_id": node_id, "status": "completed"}


@router.post("/run/{run_id}/retry/{node_id}")
async def retry_node(run_id: str, node_id: str, action: DAGNodeAction = None):
    """Retry a failed node."""
    if run_id not in dag_runs:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    run = dag_runs[run_id]
    if node_id not in run["node_statuses"]:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")

    run["node_statuses"][node_id] = {"status": "pending", "progress_pct": 0.0}
    run["updated_at"] = datetime.now(timezone.utc).isoformat()

    await _emit_event(run_id, {
        "type": "node_update",
        "node_id": node_id,
        "status": "pending",
        "progress_pct": 0.0,
    })

    return {"node_id": node_id, "status": "pending", "message": "Node queued for retry"}


@router.post("/run/{run_id}/skip/{node_id}")
async def skip_node(run_id: str, node_id: str, action: DAGNodeAction = None):
    """Skip a node (mark as skipped so downstream can proceed)."""
    if run_id not in dag_runs:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    run = dag_runs[run_id]
    if node_id not in run["node_statuses"]:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")

    run["node_statuses"][node_id] = {"status": "skipped", "progress_pct": 0.0}
    run["updated_at"] = datetime.now(timezone.utc).isoformat()

    await _emit_event(run_id, {
        "type": "node_update",
        "node_id": node_id,
        "status": "skipped",
        "progress_pct": 0.0,
    })

    return {"node_id": node_id, "status": "skipped"}


@router.get("/runs")
async def list_dag_runs(
    work_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
):
    """List recent DAG runs with optional filtering."""
    runs = list(dag_runs.values())

    if work_id:
        runs = [r for r in runs if r["work_id"] == work_id]
    if status:
        runs = [r for r in runs if r["status"] == status]

    runs.sort(key=lambda r: r["created_at"], reverse=True)
    runs = runs[:limit]

    # Return summaries only
    return [
        {
            "run_id": r["run_id"],
            "work_id": r["work_id"],
            "volumes": r["volumes"],
            "pipeline_version": r["pipeline_version"],
            "status": r["status"],
            "overall_progress_pct": _compute_progress(r),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "current_node": r.get("current_node"),
            "batch_id": r.get("batch_id"),
        }
        for r in runs
    ]
