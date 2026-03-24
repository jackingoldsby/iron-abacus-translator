"""
Workflow Template Models

Defines workflow templates (blueprints) that can be executed on works.
Templates have Docker-style random IDs (e.g., "clever_turing") and
variable-length stage definitions.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class WorkflowStageDefinition(BaseModel):
    """Definition of a single stage in a workflow template"""
    number: int = Field(..., description="Stage number (1-based)")
    name: str = Field(..., description="Stage identifier (e.g., 'metadata', 'body')")
    display_name: str = Field(..., description="Human-readable stage name")
    icon: str = Field(default="⚙️", description="Emoji icon for display")
    description: Optional[str] = Field(None, description="Stage description")
    is_parallel: bool = Field(default=False, description="Can run in parallel with other stages")
    requires_footnotes: bool = Field(default=False, description="Whether this stage generates footnotes")


class WorkflowTemplate(BaseModel):
    """
    Workflow template (blueprint) defining a processing pipeline.

    Uses Docker-style random IDs (e.g., "clever_turing") as immutable identifiers,
    with editable display names for clarity.
    """
    workflow_id: str = Field(..., description="Unique workflow ID (e.g., 'clever_turing')")
    name: str = Field(..., description="Display name (e.g., 'Complete Translation Pipeline')")
    description: str = Field(..., description="Workflow description")
    version: str = Field(default="1.0", description="Template version")

    stages: List[WorkflowStageDefinition] = Field(..., description="Variable-length stage definitions")

    default_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Default configuration for runs"
    )

    # Metadata
    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="Creation timestamp"
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="Last update timestamp"
    )

    # Permissions
    is_system_template: bool = Field(
        default=False,
        description="System-provided template (cannot be deleted)"
    )
    is_editable: bool = Field(
        default=True,
        description="Whether users can edit this template"
    )

    # Stats (optional)
    run_count: int = Field(default=0, description="Number of times this workflow has been run")
    success_rate: float = Field(default=0.0, description="Success rate (0-100)")

    class Config:
        schema_extra = {
            "example": {
                "workflow_id": "clever_turing",
                "name": "Complete Translation Pipeline",
                "description": "Full translation with cultural footnotes and validation",
                "version": "1.0",
                "stages": [
                    {
                        "number": 1,
                        "name": "metadata",
                        "display_name": "Metadata",
                        "icon": "📋",
                        "description": "Translate work metadata",
                        "requires_footnotes": False
                    },
                    {
                        "number": 2,
                        "name": "body",
                        "display_name": "Body Content",
                        "icon": "📄",
                        "description": "Translate main content with cultural footnotes",
                        "is_parallel": True,
                        "requires_footnotes": True
                    }
                ],
                "default_config": {
                    "max_workers": 3,
                    "enable_checkpoints": True
                },
                "is_system_template": True,
                "is_editable": False
            }
        }


class WorkflowTemplateList(BaseModel):
    """List of workflow templates"""
    templates: List[WorkflowTemplate]
    total: int


class WorkflowTemplateCreate(BaseModel):
    """Request to create a new workflow template"""
    name: str
    description: str
    stages: List[WorkflowStageDefinition]
    default_config: Dict[str, Any] = Field(default_factory=dict)

    # workflow_id will be auto-generated using Docker-style naming


class WorkflowTemplateUpdate(BaseModel):
    """Request to update a workflow template"""
    name: Optional[str] = None
    description: Optional[str] = None
    stages: Optional[List[WorkflowStageDefinition]] = None
    default_config: Optional[Dict[str, Any]] = None
    is_editable: Optional[bool] = None
