"""
Workflows for Book Processing

Provides DAG-based pipeline orchestration with:
- Topological execution order
- Parallel execution
- Quality gates
- DuckDB progress tracking
- Web UI integration
"""

from .dag_engine import DAGDefinition, NodeStatus
from .translation_pipeline_dag import create_v2_pipeline_dag

__all__ = ["DAGDefinition", "NodeStatus", "create_v2_pipeline_dag"]
