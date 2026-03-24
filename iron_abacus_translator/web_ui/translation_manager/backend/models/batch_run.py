"""
Batch Run Models

Defines batch workflow runs that process multiple works using the same workflow template.
Provides aggregate progress tracking across all individual runs.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class BatchWorkflowRun(BaseModel):
    """
    Batch workflow run - processes multiple works using same workflow template.

    Tracks aggregate progress and provides expandable view of individual runs.
    """
    batch_id: str = Field(..., description="Unique batch identifier (e.g., 'batch_abc123')")

    # Workflow info
    workflow_id: str = Field(..., description="Workflow template ID (e.g., 'clever_turing')")
    workflow_name: str = Field(..., description="Workflow display name for UI")

    # Works being processed
    work_ids: List[str] = Field(..., description="List of work IDs in this batch")
    individual_runs: List[str] = Field(
        default_factory=list,
        description="List of flow_run_ids for individual work runs"
    )

    # Status
    status: str = Field(
        ...,
        description="Overall batch status: scheduled, running, completed, partial_failure, failed, cancelled"
    )

    # Aggregate progress
    overall_progress_pct: float = Field(default=0.0, description="Aggregate progress (0-100)")
    completed_count: int = Field(default=0, description="Number of completed work runs")
    failed_count: int = Field(default=0, description="Number of failed work runs")
    running_count: int = Field(default=0, description="Number of running work runs")
    pending_count: int = Field(default=0, description="Number of pending work runs")

    # Timing
    start_time: Optional[str] = Field(None, description="Batch start time (ISO format)")
    end_time: Optional[str] = Field(None, description="Batch end time (ISO format)")
    duration_seconds: Optional[float] = Field(None, description="Total duration in seconds")

    # Configuration
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Batch configuration"
    )

    # Metadata
    created_by: Optional[str] = Field(None, description="User who created the batch")
    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="Creation timestamp"
    )

    class Config:
        schema_extra = {
            "example": {
                "batch_id": "batch_abc123",
                "workflow_id": "clever_turing",
                "workflow_name": "Complete Translation Pipeline",
                "work_ids": ["D1379", "I1046", "D0055"],
                "individual_runs": [
                    "uuid-run-001",
                    "uuid-run-002",
                    "uuid-run-003"
                ],
                "status": "running",
                "overall_progress_pct": 67.5,
                "completed_count": 1,
                "failed_count": 0,
                "running_count": 1,
                "pending_count": 1,
                "start_time": "2025-01-15T10:30:00Z"
            }
        }


class BatchWorkflowRunCreate(BaseModel):
    """Request to create a batch workflow run"""
    workflow_id: str = Field(..., description="Which workflow template to use")
    work_ids: List[str] = Field(..., description="Works to process")
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Configuration overrides"
    )


class BatchWorkflowRunStatus(BaseModel):
    """
    Detailed batch run status with individual run details.

    Used for the expanded batch view in Job Monitor.
    """
    batch_id: str
    workflow_id: str
    workflow_name: str
    status: str
    overall_progress_pct: float

    # Aggregate counts
    completed_count: int
    failed_count: int
    running_count: int
    pending_count: int
    total_count: int

    # Individual run statuses
    individual_run_statuses: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of individual run status objects"
    )

    # Timing
    start_time: Optional[str]
    end_time: Optional[str]
    duration_seconds: Optional[float]

    class Config:
        schema_extra = {
            "example": {
                "batch_id": "batch_abc123",
                "workflow_id": "clever_turing",
                "workflow_name": "Complete Translation Pipeline",
                "status": "running",
                "overall_progress_pct": 67.5,
                "completed_count": 1,
                "failed_count": 0,
                "running_count": 1,
                "pending_count": 1,
                "total_count": 3,
                "individual_run_statuses": [
                    {
                        "run_id": "uuid-run-001",
                        "work_id": "D1379",
                        "status": "completed",
                        "progress_pct": 100.0
                    },
                    {
                        "run_id": "uuid-run-002",
                        "work_id": "I1046",
                        "status": "running",
                        "progress_pct": 45.0
                    },
                    {
                        "run_id": "uuid-run-003",
                        "work_id": "D0055",
                        "status": "pending",
                        "progress_pct": 0.0
                    }
                ]
            }
        }


class BatchWorkflowRunList(BaseModel):
    """List of batch workflow runs"""
    batches: List[BatchWorkflowRun]
    total: int
