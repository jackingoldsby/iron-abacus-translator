#!/usr/bin/env python3
"""
Workflow API Endpoints

Provides REST API for Prefect workflow orchestration:
- Start/stop/pause workflows
- Query workflow status and progress
- Server-Sent Events (SSE) for real-time updates
- Workflow artifact retrieval (validation reports, logs)

Integrates Prefect with the existing translation_manager UI.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from prefect import get_client
from prefect.client.schemas.filters import FlowRunFilter, FlowFilter, LogFilter
from prefect.client.schemas.sorting import FlowRunSort
from prefect.states import Failed, Paused, Running

# Import workflow template and batch run models
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from models.workflow_template import WorkflowTemplate, WorkflowTemplateList
from models.batch_run import (
    BatchWorkflowRun,
    BatchWorkflowRunCreate,
    BatchWorkflowRunStatus,
    BatchWorkflowRunList
)

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/workflow", tags=["workflow"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class WorkflowStartRequest(BaseModel):
    """Request to start a new workflow"""
    workflow_id: str = Field(..., description="Workflow template ID (e.g., 'clever_turing')")
    work_id: str = Field(..., description="Work identifier (e.g., D1379)")
    volume: Optional[str] = Field(None, description="Optional volume identifier")
    config: Dict[str, Any] = Field(default_factory=dict, description="Workflow configuration")
    resume: bool = Field(False, description="Resume from checkpoint if available")


class WorkflowStageStatus(BaseModel):
    """Status of a single workflow stage"""
    stage_name: str
    stage_number: int
    status: str  # pending, running, completed, failed, skipped
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: Optional[float] = None
    items_processed: int = 0
    success_count: int = 0
    error_count: int = 0
    progress_pct: float = 0.0
    validation_status: Optional[str] = None  # For quality gates


class WorkflowStatus(BaseModel):
    """Complete workflow status"""
    flow_run_id: str
    workflow_id: str = Field(..., description="Workflow template ID")
    workflow_name: str = Field(..., description="Workflow display name")
    work_id: str
    volume: Optional[str] = None
    status: str  # scheduled, pending, running, completed, failed, cancelled
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: Optional[float] = None
    overall_progress_pct: float = 0.0
    current_stage: Optional[str] = None
    stages: List[WorkflowStageStatus] = Field(default_factory=list)
    error_message: Optional[str] = None
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)  # Validation reports, logs


class WorkflowListItem(BaseModel):
    """Summary for workflow list"""
    flow_run_id: str
    workflow_id: str = Field(..., description="Workflow template ID")
    workflow_name: str = Field(..., description="Workflow display name")
    work_id: str
    volume: Optional[str] = None
    status: str
    start_time: Optional[str] = None
    duration_seconds: Optional[float] = None
    overall_progress_pct: float = 0.0


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

async def get_flow_deployment_id(flow_name: str = "translation-pipeline") -> Optional[str]:
    """Get deployment ID for a flow by name."""
    try:
        async with get_client() as client:
            deployments = await client.read_deployments(
                flow_filter=FlowFilter(name={"any_": [flow_name]})
            )
            if deployments:
                return str(deployments[0].id)
            return None
    except Exception as e:
        logger.error(f"Error getting deployment: {e}")
        return None


async def extract_workflow_status(flow_run) -> WorkflowStatus:
    """Extract workflow status from Prefect flow run."""

    # Calculate progress from task runs
    overall_progress = 0.0
    stages = []
    current_stage = None

    # Get task runs for this flow
    async with get_client() as client:
        task_runs = await client.read_task_runs(
            flow_run_filter=FlowRunFilter(id={"any_": [flow_run.id]})
        )

        # Group task runs by stage
        stage_tasks = {}
        for task_run in task_runs:
            task_name = task_run.name
            stage_tasks.setdefault(task_name, []).append(task_run)

        # Calculate stage status
        total_stages = len(stage_tasks) if stage_tasks else 7  # Default 7 stages
        completed_stages = 0

        for stage_num, (stage_name, tasks) in enumerate(stage_tasks.items(), 1):
            # Aggregate task status
            total_tasks = len(tasks)
            completed_tasks = sum(1 for t in tasks if t.state and t.state.is_completed())
            failed_tasks = sum(1 for t in tasks if t.state and t.state.is_failed())
            running_tasks = sum(1 for t in tasks if t.state and t.state.is_running())

            if failed_tasks > 0:
                stage_status = "failed"
            elif running_tasks > 0:
                stage_status = "running"
                current_stage = stage_name
            elif completed_tasks == total_tasks:
                stage_status = "completed"
                completed_stages += 1
            else:
                stage_status = "pending"

            stage_progress = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0

            # Get timing info
            start_times = [t.start_time for t in tasks if t.start_time]
            end_times = [t.end_time for t in tasks if t.end_time]

            stage_start = min(start_times).isoformat() if start_times else None
            stage_end = max(end_times).isoformat() if end_times else None

            duration = None
            if start_times and end_times:
                duration = (max(end_times) - min(start_times)).total_seconds()

            stages.append(WorkflowStageStatus(
                stage_name=stage_name,
                stage_number=stage_num,
                status=stage_status,
                start_time=stage_start,
                end_time=stage_end,
                duration_seconds=duration,
                items_processed=total_tasks,
                success_count=completed_tasks,
                error_count=failed_tasks,
                progress_pct=stage_progress
            ))

        overall_progress = (completed_stages / total_stages * 100) if total_stages > 0 else 0

    # Extract parameters
    work_id = "unknown"
    volume = None
    workflow_id = "unknown"
    workflow_name = "Unknown Workflow"
    if flow_run.parameters:
        work_id = flow_run.parameters.get("work_id", "unknown")
        volume = flow_run.parameters.get("volume")
        workflow_id = flow_run.parameters.get("workflow_id", "unknown")
        workflow_name = flow_run.parameters.get("workflow_name", "Unknown Workflow")

    # Calculate duration
    duration = None
    if flow_run.start_time:
        end = flow_run.end_time or datetime.now(timezone.utc)
        duration = (end - flow_run.start_time).total_seconds()

    return WorkflowStatus(
        flow_run_id=str(flow_run.id),
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        work_id=work_id,
        volume=volume,
        status=flow_run.state.name.lower() if flow_run.state else "unknown",
        start_time=flow_run.start_time.isoformat() if flow_run.start_time else None,
        end_time=flow_run.end_time.isoformat() if flow_run.end_time else None,
        duration_seconds=duration,
        overall_progress_pct=overall_progress,
        current_stage=current_stage,
        stages=stages,
        error_message=flow_run.state.message if flow_run.state and flow_run.state.is_failed() else None
    )


# =============================================================================
# API ENDPOINTS
# =============================================================================

@router.post("/start", response_model=WorkflowStatus)
async def start_workflow(request: WorkflowStartRequest):
    """
    Start a new translation workflow.

    Returns:
        Initial workflow status with flow_run_id for tracking
    """
    try:
        # Validate workflow template exists
        templates_dir = Path(__file__).parent.parent / "workflow_templates"
        template_file = templates_dir / f"{request.workflow_id}.json"

        if not template_file.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Workflow template '{request.workflow_id}' not found"
            )

        # Load template to get workflow name
        with open(template_file, 'r') as f:
            template_data = json.load(f)
            workflow_name = template_data.get("name", "Unknown Workflow")

        # Import DAG pipeline runner (avoid circular import at module level)
        from scripts.pipeline_runner import build_pipeline, RunnerConfig

        # Create config from request
        runner_config = RunnerConfig(**request.config) if request.config else RunnerConfig()

        # Build and run pipeline in background thread
        from concurrent.futures import ThreadPoolExecutor

        executor = ThreadPoolExecutor(max_workers=1)

        def run_pipeline_sync():
            """Run DAG pipeline synchronously in background thread"""
            try:
                runner = build_pipeline(runner_config)
                result = runner.run(
                    request.work_id,
                    volume=request.volume,
                    resume=request.resume,
                )
                logger.info(f"Pipeline completed for {request.work_id}")
                return result
            except Exception as e:
                logger.error(f"Pipeline error for {request.work_id}: {e}", exc_info=True)
                raise

        # Submit to executor (non-blocking)
        future = executor.submit(run_pipeline_sync)

        logger.info(f"Started pipeline ({workflow_name}) for work {request.work_id}")

        # Return initial status — the DAG runner tracks progress in DuckDB,
        # so the /status endpoint can query it directly.
        return WorkflowStatus(
            flow_run_id=f"dag-{request.work_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            workflow_id=request.workflow_id,
            workflow_name=workflow_name,
            work_id=request.work_id,
            volume=request.volume,
            status="running",
            start_time=datetime.now(timezone.utc).isoformat(),
            overall_progress_pct=0.0,
            stages=[],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{flow_run_id}", response_model=WorkflowStatus)
async def get_workflow_status(flow_run_id: str):
    """
    Get current status of a workflow.

    Args:
        flow_run_id: Flow run identifier

    Returns:
        Complete workflow status with stage details
    """
    try:
        async with get_client() as client:
            flow_run = await client.read_flow_run(flow_run_id)
            return await extract_workflow_status(flow_run)

    except Exception as e:
        logger.error(f"Error getting workflow status: {e}")
        raise HTTPException(status_code=404, detail=f"Workflow {flow_run_id} not found")


@router.get("/list", response_model=List[WorkflowListItem])
async def list_workflows(limit: int = 50, status: Optional[str] = None):
    """
    List recent workflows.

    Args:
        limit: Maximum number of workflows to return
        status: Filter by status (running, completed, failed, etc.)

    Returns:
        List of workflow summaries
    """
    try:
        async with get_client() as client:
            # Build filter
            flow_run_filter = None
            if status:
                flow_run_filter = FlowRunFilter(
                    state={"type": {"any_": [status.upper()]}}
                )

            # Query flow runs
            flow_runs = await client.read_flow_runs(
                flow_run_filter=flow_run_filter,
                limit=limit,
                sort=FlowRunSort.START_TIME_DESC
            )

            # Convert to list items
            items = []
            for flow_run in flow_runs:
                work_id = flow_run.parameters.get("work_id", "unknown") if flow_run.parameters else "unknown"
                volume = flow_run.parameters.get("volume") if flow_run.parameters else None
                workflow_id = flow_run.parameters.get("workflow_id", "unknown") if flow_run.parameters else "unknown"
                workflow_name = flow_run.parameters.get("workflow_name", "Unknown Workflow") if flow_run.parameters else "Unknown Workflow"

                duration = None
                if flow_run.start_time:
                    end = flow_run.end_time or datetime.now(timezone.utc)
                    duration = (end - flow_run.start_time).total_seconds()

                items.append(WorkflowListItem(
                    flow_run_id=str(flow_run.id),
                    workflow_id=workflow_id,
                    workflow_name=workflow_name,
                    work_id=work_id,
                    volume=volume,
                    status=flow_run.state.name.lower() if flow_run.state else "unknown",
                    start_time=flow_run.start_time.isoformat() if flow_run.start_time else None,
                    duration_seconds=duration,
                    overall_progress_pct=0.0  # TODO: Calculate from tasks
                ))

            return items

    except Exception as e:
        logger.error(f"Error listing workflows: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{flow_run_id}")
async def cancel_workflow(flow_run_id: str, delete_files: bool = False):
    """
    Cancel a running workflow and optionally delete all WIP/log files.

    Args:
        flow_run_id: Flow run identifier
        delete_files: If True, also deletes all WIP and log files for this workflow.
                     If False (default), only cancels the workflow.

    Returns:
        Cancellation confirmation with deletion info if applicable
    """
    try:
        async with get_client() as client:
            # Cancel the flow run
            await client.set_flow_run_state(
                flow_run_id=flow_run_id,
                state=Failed(message="Cancelled by user"),
                force=True
            )

            logger.info(f"Cancelled workflow {flow_run_id}")

            result = {
                "status": "cancelled",
                "flow_run_id": flow_run_id,
                "files_deleted": False
            }

            # Optionally delete all files
            if delete_files:
                try:
                    deletion_result = await delete_all_results(flow_run_id)
                    result["files_deleted"] = True
                    result["deletion_details"] = deletion_result
                    logger.info(f"Deleted all files for workflow {flow_run_id}")
                except Exception as delete_error:
                    logger.error(f"Error deleting files for workflow {flow_run_id}: {delete_error}")
                    result["deletion_error"] = str(delete_error)

            return result

    except Exception as e:
        logger.error(f"Error cancelling workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pause/{flow_run_id}")
async def pause_workflow(flow_run_id: str):
    """
    Pause a running workflow.

    Args:
        flow_run_id: Flow run identifier

    Returns:
        Pause confirmation with current state
    """
    try:
        async with get_client() as client:
            # Get current flow run state
            flow_run = await client.read_flow_run(flow_run_id)

            # Check if workflow is in a pausable state (Running)
            if flow_run.state.type.value not in ['RUNNING', 'SCHEDULED']:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot pause workflow in state: {flow_run.state.type.value}"
                )

            # Pause the flow run
            await client.set_flow_run_state(
                flow_run_id=flow_run_id,
                state=Paused(message="Paused by user"),
                force=True
            )

            logger.info(f"Paused workflow {flow_run_id}")
            return {
                "status": "paused",
                "flow_run_id": flow_run_id,
                "previous_state": flow_run.state.type.value
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error pausing workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resume/{flow_run_id}")
async def resume_workflow(flow_run_id: str):
    """
    Resume a paused workflow.

    Args:
        flow_run_id: Flow run identifier

    Returns:
        Resume confirmation with current state
    """
    try:
        async with get_client() as client:
            # Get current flow run state
            flow_run = await client.read_flow_run(flow_run_id)

            # Check if workflow is paused
            if flow_run.state.type.value != 'PAUSED':
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot resume workflow in state: {flow_run.state.type.value}"
                )

            # Resume the flow run
            await client.set_flow_run_state(
                flow_run_id=flow_run_id,
                state=Running(message="Resumed by user"),
                force=True
            )

            logger.info(f"Resumed workflow {flow_run_id}")
            return {
                "status": "resumed",
                "flow_run_id": flow_run_id,
                "new_state": "RUNNING"
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resuming workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rollback/{flow_run_id}")
async def rollback_workflow(flow_run_id: str, target_stage: int):
    """
    Rollback workflow to a specific stage by deleting WIP files and logs
    for all stages after the target stage.

    Args:
        flow_run_id: Flow run identifier
        target_stage: Stage number to rollback to (1-7)

    Returns:
        Rollback confirmation with deleted stages info
    """
    if target_stage < 1 or target_stage > 7:
        raise HTTPException(status_code=400, detail="Target stage must be between 1 and 7")

    try:
        async with get_client() as client:
            # Get workflow status to get work_id
            flow_run = await client.read_flow_run(flow_run_id)

            # Extract work_id from flow run parameters
            work_id = None
            if flow_run.parameters:
                work_id = flow_run.parameters.get('work_id')

            if not work_id:
                raise HTTPException(status_code=404, detail="Work ID not found in workflow parameters")

            deleted_stages = []
            deleted_files = []

            # Delete WIP files and logs for stages after target
            for stage_num in range(target_stage + 1, 8):
                stage_config = PIPELINE_STAGES.get(stage_num)
                if not stage_config:
                    continue

                stage_name = stage_config['name']
                wip_dir = WIP_BASE_DIR / stage_config['dir']

                # Find and delete WIP files for this work
                wip_pattern = f"*{work_id}*.json"
                wip_files = list(wip_dir.glob(wip_pattern))

                for wip_file in wip_files:
                    try:
                        wip_file.unlink()
                        deleted_files.append(str(wip_file))
                        logger.info(f"Deleted WIP file: {wip_file}")
                    except Exception as e:
                        logger.warning(f"Failed to delete {wip_file}: {e}")

                # Delete stage log
                log_file = LOG_BASE_DIR / f"{work_id}_stage_{stage_num}_{stage_name}.json"
                if log_file.exists():
                    try:
                        log_file.unlink()
                        deleted_files.append(str(log_file))
                        logger.info(f"Deleted log file: {log_file}")
                    except Exception as e:
                        logger.warning(f"Failed to delete {log_file}: {e}")

                deleted_stages.append({
                    'stage_num': stage_num,
                    'stage_name': stage_name,
                    'files_deleted': len([f for f in deleted_files if stage_name in f or f"stage_{stage_num}" in f])
                })

            logger.info(f"Rolled back workflow {flow_run_id} to stage {target_stage}. Deleted {len(deleted_files)} files.")

            return {
                "status": "rolled_back",
                "flow_run_id": flow_run_id,
                "work_id": work_id,
                "target_stage": target_stage,
                "deleted_stages": deleted_stages,
                "total_files_deleted": len(deleted_files)
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rolling back workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/stage/{flow_run_id}/{stage_num}")
async def delete_stage_results(flow_run_id: str, stage_num: int):
    """
    Delete WIP files and logs for a specific stage.

    Args:
        flow_run_id: Flow run identifier
        stage_num: Stage number to delete (1-7)

    Returns:
        Deletion confirmation with file count
    """
    if stage_num < 1 or stage_num > 7:
        raise HTTPException(status_code=400, detail="Stage number must be between 1 and 7")

    try:
        async with get_client() as client:
            # Get workflow status to get work_id
            flow_run = await client.read_flow_run(flow_run_id)

            # Extract work_id from flow run parameters
            work_id = None
            if flow_run.parameters:
                work_id = flow_run.parameters.get('work_id')

            if not work_id:
                raise HTTPException(status_code=404, detail="Work ID not found in workflow parameters")

            deleted_files = []
            stage_config = PIPELINE_STAGES.get(stage_num)

            if not stage_config:
                raise HTTPException(status_code=404, detail=f"Stage {stage_num} configuration not found")

            stage_name = stage_config['name']
            wip_dir = WIP_BASE_DIR / stage_config['dir']

            # Find and delete WIP files for this work and stage
            wip_pattern = f"*{work_id}*.json"
            wip_files = list(wip_dir.glob(wip_pattern))

            for wip_file in wip_files:
                try:
                    wip_file.unlink()
                    deleted_files.append(str(wip_file))
                    logger.info(f"Deleted WIP file: {wip_file}")
                except Exception as e:
                    logger.warning(f"Failed to delete {wip_file}: {e}")

            # Delete stage log
            log_file = LOG_BASE_DIR / f"{work_id}_stage_{stage_num}_{stage_name}.json"
            if log_file.exists():
                try:
                    log_file.unlink()
                    deleted_files.append(str(log_file))
                    logger.info(f"Deleted log file: {log_file}")
                except Exception as e:
                    logger.warning(f"Failed to delete {log_file}: {e}")

            logger.info(f"Deleted stage {stage_num} results for workflow {flow_run_id}. Deleted {len(deleted_files)} files.")

            return {
                "status": "deleted",
                "flow_run_id": flow_run_id,
                "work_id": work_id,
                "stage_num": stage_num,
                "stage_name": stage_name,
                "files_deleted": deleted_files,
                "total_files_deleted": len(deleted_files)
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting stage results: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/all/{flow_run_id}")
async def delete_all_results(flow_run_id: str):
    """
    Delete all WIP files and logs for a workflow.

    Args:
        flow_run_id: Flow run identifier

    Returns:
        Deletion confirmation with file count
    """
    try:
        async with get_client() as client:
            # Get workflow status to get work_id
            flow_run = await client.read_flow_run(flow_run_id)

            # Extract work_id from flow run parameters
            work_id = None
            if flow_run.parameters:
                work_id = flow_run.parameters.get('work_id')

            if not work_id:
                raise HTTPException(status_code=404, detail="Work ID not found in workflow parameters")

            deleted_files = []
            deleted_stages = []

            # Delete WIP files and logs for all stages
            for stage_num in range(1, 8):
                stage_config = PIPELINE_STAGES.get(stage_num)
                if not stage_config:
                    continue

                stage_name = stage_config['name']
                wip_dir = WIP_BASE_DIR / stage_config['dir']

                # Find and delete WIP files for this work
                wip_pattern = f"*{work_id}*.json"
                wip_files = list(wip_dir.glob(wip_pattern))

                stage_deleted_count = 0
                for wip_file in wip_files:
                    try:
                        wip_file.unlink()
                        deleted_files.append(str(wip_file))
                        stage_deleted_count += 1
                        logger.info(f"Deleted WIP file: {wip_file}")
                    except Exception as e:
                        logger.warning(f"Failed to delete {wip_file}: {e}")

                # Delete stage log
                log_file = LOG_BASE_DIR / f"{work_id}_stage_{stage_num}_{stage_name}.json"
                if log_file.exists():
                    try:
                        log_file.unlink()
                        deleted_files.append(str(log_file))
                        stage_deleted_count += 1
                        logger.info(f"Deleted log file: {log_file}")
                    except Exception as e:
                        logger.warning(f"Failed to delete {log_file}: {e}")

                if stage_deleted_count > 0:
                    deleted_stages.append({
                        'stage_num': stage_num,
                        'stage_name': stage_name,
                        'files_deleted': stage_deleted_count
                    })

            logger.info(f"Deleted all results for workflow {flow_run_id}. Deleted {len(deleted_files)} files from {len(deleted_stages)} stages.")

            return {
                "status": "deleted",
                "flow_run_id": flow_run_id,
                "work_id": work_id,
                "deleted_stages": deleted_stages,
                "total_files_deleted": len(deleted_files)
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting all results: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stream/{flow_run_id}")
async def stream_workflow_progress(flow_run_id: str):
    """
    Server-Sent Events (SSE) stream for real-time workflow progress.

    Args:
        flow_run_id: Flow run identifier

    Returns:
        SSE stream with periodic status updates
    """
    async def event_generator():
        """Generate SSE events with workflow status."""
        previous_status_dict = None

        try:
            while True:
                # Get current status
                async with get_client() as client:
                    flow_run = await client.read_flow_run(flow_run_id)
                    status = await extract_workflow_status(flow_run)

                    # Convert to dict for comparison
                    current_status_dict = status.dict()

                    # Only send if status actually changed (deep comparison)
                    if previous_status_dict is None or current_status_dict != previous_status_dict:
                        data = json.dumps(current_status_dict)
                        yield f"data: {data}\n\n"
                        previous_status_dict = current_status_dict
                        logger.debug(f"SSE: Sent updated status for flow {flow_run_id}")
                    else:
                        logger.debug(f"SSE: No changes for flow {flow_run_id}, skipping update")

                    # Stop streaming if workflow is complete
                    if status.status in ["completed", "failed", "cancelled"]:
                        break

                # Wait before next update (2s for running, 5s for stable states)
                sleep_interval = 2 if status.status == 'running' else 5
                await asyncio.sleep(sleep_interval)

        except Exception as e:
            logger.error(f"Error in SSE stream: {e}")
            error_data = json.dumps({"error": str(e)})
            yield f"data: {error_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


@router.get("/logs/{flow_run_id}")
async def get_workflow_logs(
    flow_run_id: str,
    limit: int = 200,
    offset: int = 0
):
    """
    Get detailed task logs for a workflow run.
    Includes granular messages like OpenAI API responses, content translation progress, etc.

    Args:
        flow_run_id: Flow run identifier
        limit: Maximum number of log entries to return
        offset: Number of log entries to skip

    Returns:
        List of log entries with timestamps, levels, and messages
    """
    try:
        async with get_client() as client:
            # Get all task runs for this flow
            task_runs = await client.read_task_runs(
                flow_run_filter=FlowRunFilter(id={"any_": [flow_run_id]}),
                limit=100
            )

            # Collect logs from all task runs
            all_logs = []
            for task_run in task_runs:
                # Read logs for this task run
                logs = await client.read_logs(
                    log_filter=LogFilter(
                        task_run_id={"any_": [str(task_run.id)]}
                    ),
                    limit=100
                )

                for log in logs:
                    all_logs.append({
                        "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                        "level": log.level,
                        "message": log.message,
                        "task_name": task_run.name,
                        "task_id": str(task_run.id)
                    })

            # Sort by timestamp (newest first)
            all_logs.sort(key=lambda x: x["timestamp"] or "", reverse=True)

            # Apply pagination
            paginated_logs = all_logs[offset:offset + limit]

            return {
                "total": len(all_logs),
                "offset": offset,
                "limit": limit,
                "logs": paginated_logs
            }

    except Exception as e:
        logger.error(f"Error fetching workflow logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/artifacts/{flow_run_id}")
async def get_workflow_artifacts(flow_run_id: str):
    """
    Get workflow artifacts (validation reports, logs, etc.).

    Args:
        flow_run_id: Flow run identifier

    Returns:
        List of artifacts with download links
    """
    try:
        async with get_client() as client:
            # Get artifacts for this flow run
            artifacts = await client.read_artifacts(
                flow_run_filter=FlowRunFilter(id={"any_": [flow_run_id]})
            )

            return [
                {
                    "key": artifact.key,
                    "type": artifact.type,
                    "description": artifact.description,
                    "created": artifact.created.isoformat(),
                    "data": artifact.data
                }
                for artifact in artifacts
            ]

    except Exception as e:
        logger.error(f"Error getting artifacts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# WIP FILE ENDPOINTS (Phase 3)
# =============================================================================

async def get_work_id_from_flow_run(flow_run_id: str) -> str:
    """Helper: Extract work_id from flow run parameters."""
    async with get_client() as client:
        flow_run = await client.read_flow_run(flow_run_id)
        if flow_run.parameters and "work_id" in flow_run.parameters:
            return flow_run.parameters["work_id"]
        raise HTTPException(404, "Work ID not found in flow run parameters")


# Pipeline stage configuration (matches translation_pipeline_dag.py)
PIPELINE_STAGES = {
    1: {"name": "body", "dir": "stage_1_body"},
    2: {"name": "metadata", "dir": "stage_2_metadata"},
    3: {"name": "toc", "dir": "stage_3_toc"},
    4: {"name": "headings", "dir": "stage_4_headings"},
    5: {"name": "special", "dir": "stage_5_special"},
    6: {"name": "cleanup", "dir": "stage_6_cleanup"},
    7: {"name": "validation", "dir": "stage_7_validation"},
}

# Default paths (from environment config)
from utils.environment_config import get_or_create_config as _get_config
_wf_env = _get_config()
WIP_BASE_DIR = _wf_env.wip_dir
LOG_BASE_DIR = _wf_env.log_dir


@router.get("/wip/stages/{flow_run_id}")
async def list_wip_stages(flow_run_id: str):
    """
    List all WIP stages for a workflow.

    Args:
        flow_run_id: Flow run identifier

    Returns:
        List of available WIP files by stage
    """
    try:
        work_id = await get_work_id_from_flow_run(flow_run_id)

        stages = []
        for stage_num, stage_info in PIPELINE_STAGES.items():
            stage_dir = WIP_BASE_DIR / stage_info["dir"]
            wip_file = stage_dir / f"{work_id}.json"

            if wip_file.exists():
                stat = wip_file.stat()
                stages.append({
                    "stage_num": stage_num,
                    "stage_name": stage_info["name"],
                    "timestamp": stat.st_mtime,
                    "file_size": stat.st_size,
                    "exists": True
                })
            else:
                stages.append({
                    "stage_num": stage_num,
                    "stage_name": stage_info["name"],
                    "exists": False
                })

        return stages

    except Exception as e:
        logger.error(f"Error listing WIP stages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wip/stage/{flow_run_id}/{stage_num}")
async def get_wip_content(flow_run_id: str, stage_num: int):
    """
    Get WIP file content from a specific stage.

    Args:
        flow_run_id: Flow run identifier
        stage_num: Stage number (1-7)

    Returns:
        WIP file JSON content
    """
    try:
        if stage_num not in PIPELINE_STAGES:
            raise HTTPException(400, f"Invalid stage number: {stage_num}")

        work_id = await get_work_id_from_flow_run(flow_run_id)
        stage_info = PIPELINE_STAGES[stage_num]
        wip_file = WIP_BASE_DIR / stage_info["dir"] / f"{work_id}.json"

        if not wip_file.exists():
            raise HTTPException(404, f"WIP file not found for stage {stage_num}")

        with open(wip_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting WIP content: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wip/stage/{flow_run_id}/{stage_num}/download")
async def download_wip(flow_run_id: str, stage_num: int):
    """
    Download WIP file from a specific stage.

    Args:
        flow_run_id: Flow run identifier
        stage_num: Stage number (1-7)

    Returns:
        File download response
    """
    try:
        from fastapi.responses import FileResponse

        if stage_num not in PIPELINE_STAGES:
            raise HTTPException(400, f"Invalid stage number: {stage_num}")

        work_id = await get_work_id_from_flow_run(flow_run_id)
        stage_info = PIPELINE_STAGES[stage_num]
        wip_file = WIP_BASE_DIR / stage_info["dir"] / f"{work_id}.json"

        if not wip_file.exists():
            raise HTTPException(404, f"WIP file not found for stage {stage_num}")

        filename = f"{work_id}_stage_{stage_num}_{stage_info['name']}.json"
        return FileResponse(
            wip_file,
            filename=filename,
            media_type="application/json"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading WIP: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs/stage/{flow_run_id}/{stage_num}")
async def get_stage_log(flow_run_id: str, stage_num: int):
    """
    Get stage-specific log file.

    Args:
        flow_run_id: Flow run identifier
        stage_num: Stage number (1-7)

    Returns:
        Stage log JSON content
    """
    try:
        if stage_num not in PIPELINE_STAGES:
            raise HTTPException(400, f"Invalid stage number: {stage_num}")

        work_id = await get_work_id_from_flow_run(flow_run_id)
        stage_info = PIPELINE_STAGES[stage_num]
        log_file = LOG_BASE_DIR / f"{work_id}_stage_{stage_num}_{stage_info['name']}.json"

        if not log_file.exists():
            raise HTTPException(404, f"Log file not found for stage {stage_num}")

        with open(log_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting stage log: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wip/compare/{flow_run_id}")
async def compare_wip_stages(
    flow_run_id: str,
    from_stage: int = 1,
    to_stage: int = 2,
    field: Optional[str] = None
):
    """
    Compare WIP files between two stages.

    Args:
        flow_run_id: Flow run identifier
        from_stage: Source stage number (1-7)
        to_stage: Target stage number (1-7)
        field: Optional specific field to compare (e.g., 'body.chapters')

    Returns:
        Comparison result with differences
    """
    try:
        if from_stage not in PIPELINE_STAGES or to_stage not in PIPELINE_STAGES:
            raise HTTPException(400, "Invalid stage numbers")

        if from_stage >= to_stage:
            raise HTTPException(400, "from_stage must be less than to_stage")

        work_id = await get_work_id_from_flow_run(flow_run_id)

        # Load both WIP files
        from_stage_info = PIPELINE_STAGES[from_stage]
        to_stage_info = PIPELINE_STAGES[to_stage]

        from_file = WIP_BASE_DIR / from_stage_info["dir"] / f"{work_id}.json"
        to_file = WIP_BASE_DIR / to_stage_info["dir"] / f"{work_id}.json"

        if not from_file.exists() or not to_file.exists():
            raise HTTPException(404, "One or both WIP files not found")

        with open(from_file, 'r', encoding='utf-8') as f:
            from_data = json.load(f)

        with open(to_file, 'r', encoding='utf-8') as f:
            to_data = json.load(f)

        # Simple comparison result
        comparison = {
            "from_stage": from_stage,
            "to_stage": to_stage,
            "from_stage_name": from_stage_info["name"],
            "to_stage_name": to_stage_info["name"],
            "summary": {
                "from_size": len(json.dumps(from_data)),
                "to_size": len(json.dumps(to_data)),
                "size_diff": len(json.dumps(to_data)) - len(json.dumps(from_data))
            }
        }

        # If specific field requested, compare it
        if field:
            # Simple nested field access (e.g., 'body.chapters')
            def get_nested_field(data, field_path):
                parts = field_path.split('.')
                value = data
                for part in parts:
                    value = value.get(part) if isinstance(value, dict) else None
                    if value is None:
                        return None
                return value

            from_value = get_nested_field(from_data, field)
            to_value = get_nested_field(to_data, field)

            comparison["field_comparison"] = {
                "field": field,
                "from_value_type": type(from_value).__name__,
                "to_value_type": type(to_value).__name__,
                "changed": from_value != to_value
            }

        return comparison

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error comparing WIP stages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# WORKFLOW TEMPLATES
# =============================================================================

@router.get("/workflows", response_model=WorkflowTemplateList)
async def list_workflow_templates():
    """
    List available workflow templates.

    Returns:
        List of workflow templates with metadata
    """
    try:
        templates_dir = Path(__file__).parent.parent / "workflow_templates"
        templates = []

        if templates_dir.exists():
            for template_file in templates_dir.glob("*.json"):
                try:
                    with open(template_file, 'r') as f:
                        template_data = json.load(f)
                        template = WorkflowTemplate(**template_data)
                        templates.append(template)
                except Exception as e:
                    logger.error(f"Error loading template {template_file}: {e}")
                    continue

        return WorkflowTemplateList(
            templates=templates,
            total=len(templates)
        )

    except Exception as e:
        logger.error(f"Error listing workflow templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workflows/{workflow_id}", response_model=WorkflowTemplate)
async def get_workflow_template(workflow_id: str):
    """
    Get a specific workflow template by ID.

    Args:
        workflow_id: Workflow template ID (e.g., "clever_turing")

    Returns:
        Workflow template details
    """
    try:
        templates_dir = Path(__file__).parent.parent / "workflow_templates"
        template_file = templates_dir / f"{workflow_id}.json"

        if not template_file.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Workflow template '{workflow_id}' not found"
            )

        with open(template_file, 'r') as f:
            template_data = json.load(f)
            return WorkflowTemplate(**template_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading workflow template '{workflow_id}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# BATCH RUNS
# =============================================================================

# In-memory storage for batch runs (TODO: Move to database)
batch_runs: Dict[str, BatchWorkflowRun] = {}


@router.post("/runs/batch", response_model=BatchWorkflowRun)
async def start_batch_run(request: BatchWorkflowRunCreate):
    """
    Start a batch workflow run (process multiple works with same workflow).

    Args:
        request: Batch run creation request

    Returns:
        Batch run status
    """
    try:
        # Validate workflow template exists
        templates_dir = Path(__file__).parent.parent / "workflow_templates"
        template_file = templates_dir / f"{request.workflow_id}.json"

        if not template_file.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Workflow template '{request.workflow_id}' not found"
            )

        # Load template to get name
        with open(template_file, 'r') as f:
            template_data = json.load(f)
            workflow_name = template_data["name"]

        # Generate batch ID
        import uuid
        batch_id = f"batch_{uuid.uuid4().hex[:8]}"

        # Create batch run
        batch_run = BatchWorkflowRun(
            batch_id=batch_id,
            workflow_id=request.workflow_id,
            workflow_name=workflow_name,
            work_ids=request.work_ids,
            individual_runs=[],
            status="scheduled",
            overall_progress_pct=0.0,
            completed_count=0,
            failed_count=0,
            running_count=0,
            pending_count=len(request.work_ids),
            start_time=datetime.utcnow().isoformat(),
            config=request.config
        )

        # TODO: Actually start individual workflow runs for each work
        # For now, just store the batch run metadata
        batch_runs[batch_id] = batch_run

        logger.info(f"Created batch run {batch_id} for {len(request.work_ids)} works using workflow '{request.workflow_id}'")

        return batch_run

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting batch run: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/batch-runs", response_model=BatchWorkflowRunList)
async def list_batch_runs(limit: int = 50):
    """
    List batch workflow runs.

    Args:
        limit: Maximum number of batches to return

    Returns:
        List of batch runs
    """
    try:
        # Get batch runs sorted by creation time (newest first)
        sorted_batches = sorted(
            batch_runs.values(),
            key=lambda b: b.created_at,
            reverse=True
        )

        return BatchWorkflowRunList(
            batches=sorted_batches[:limit],
            total=len(batch_runs)
        )

    except Exception as e:
        logger.error(f"Error listing batch runs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/batch-runs/{batch_id}", response_model=BatchWorkflowRunStatus)
async def get_batch_run(batch_id: str):
    """
    Get detailed batch run status with individual run details.

    Args:
        batch_id: Batch run identifier

    Returns:
        Detailed batch run status
    """
    try:
        if batch_id not in batch_runs:
            raise HTTPException(
                status_code=404,
                detail=f"Batch run '{batch_id}' not found"
            )

        batch_run = batch_runs[batch_id]

        # TODO: Fetch actual individual run statuses from Prefect
        # For now, return basic status
        individual_run_statuses = []
        for i, work_id in enumerate(batch_run.work_ids):
            run_id = batch_run.individual_runs[i] if i < len(batch_run.individual_runs) else None
            individual_run_statuses.append({
                "run_id": run_id or f"pending_{i}",
                "work_id": work_id,
                "status": "pending" if not run_id else "running",
                "progress_pct": 0.0
            })

        return BatchWorkflowRunStatus(
            batch_id=batch_run.batch_id,
            workflow_id=batch_run.workflow_id,
            workflow_name=batch_run.workflow_name,
            status=batch_run.status,
            overall_progress_pct=batch_run.overall_progress_pct,
            completed_count=batch_run.completed_count,
            failed_count=batch_run.failed_count,
            running_count=batch_run.running_count,
            pending_count=batch_run.pending_count,
            total_count=len(batch_run.work_ids),
            individual_run_statuses=individual_run_statuses,
            start_time=batch_run.start_time,
            end_time=batch_run.end_time,
            duration_seconds=batch_run.duration_seconds
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting batch run '{batch_id}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prefect-ui/{path:path}")
async def prefect_proxy(path: str, request: Request):
    """
    Proxy requests to Prefect UI to avoid CORS issues.

    This allows embedding Prefect UI components in iframes without
    cross-origin restrictions.

    Args:
        path: The Prefect UI path to proxy
        request: FastAPI request object

    Returns:
        Proxied response from Prefect server
    """
    import httpx
    from fastapi.responses import StreamingResponse, Response

    prefect_url = f"http://localhost:4200/{path}"

    # Forward query parameters
    query_string = str(request.url.query)
    if query_string:
        prefect_url = f"{prefect_url}?{query_string}"

    try:
        async with httpx.AsyncClient() as client:
            # Make request to Prefect server
            response = await client.get(
                prefect_url,
                headers=dict(request.headers),
                follow_redirects=True
            )

            # Determine content type
            content_type = response.headers.get("content-type", "text/html")

            # For streaming responses (like SSE)
            if "text/event-stream" in content_type:
                async def stream():
                    async for chunk in response.aiter_bytes():
                        yield chunk

                return StreamingResponse(
                    stream(),
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=content_type
                )

            # For regular responses
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=content_type
            )

    except Exception as e:
        logger.error(f"Error proxying Prefect UI request: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to proxy Prefect UI: {str(e)}"
        )
