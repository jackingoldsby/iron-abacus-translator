#!/usr/bin/env python3
"""
DAG Workflow Engine

A lightweight DAG (Directed Acyclic Graph) engine for modeling pipeline stages
as a proper graph with dependencies, parallel groups, and quality gates.

Used by the translation pipeline to define execution order, detect parallelism,
and compute layout coordinates for visualization.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, Tuple
from collections import defaultdict, deque
from enum import Enum


class NodeType(str, Enum):
    TASK = "task"
    QUALITY_GATE = "quality_gate"
    PARALLEL_GROUP = "parallel_group"
    FAN_OUT = "fan_out"


class NodeStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class EdgeType(str, Enum):
    DEPENDENCY = "dependency"
    QUALITY_GATE = "quality_gate"
    PARALLEL = "parallel"


@dataclass
class DAGNode:
    id: str
    display_name: str
    node_type: str = NodeType.TASK
    dependencies: List[str] = field(default_factory=list)
    status: str = NodeStatus.PENDING
    progress_pct: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    validator: Optional[Callable] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "node_type": self.node_type,
            "dependencies": self.dependencies,
            "status": self.status,
            "progress_pct": self.progress_pct,
            "metadata": self.metadata,
        }


@dataclass
class DAGEdge:
    source: str
    target: str
    edge_type: str = EdgeType.DEPENDENCY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "edge_type": self.edge_type,
        }


class DAGDefinition:
    """
    Represents a complete DAG with nodes and edges.

    Provides topological sorting, parallel group detection,
    cycle validation, and layout computation for visualization.
    """

    def __init__(self):
        self.nodes: Dict[str, DAGNode] = {}
        self.edges: List[DAGEdge] = []

    def add_node(self, node: DAGNode) -> None:
        self.nodes[node.id] = node

    def add_edge(self, source: str, target: str, edge_type: str = EdgeType.DEPENDENCY) -> None:
        self.edges.append(DAGEdge(source=source, target=target, edge_type=edge_type))
        if source not in self.nodes[target].dependencies:
            self.nodes[target].dependencies.append(source)

    def topological_sort(self) -> List[str]:
        """Return node IDs in topological order using Kahn's algorithm."""
        in_degree: Dict[str, int] = {nid: 0 for nid in self.nodes}
        adjacency: Dict[str, List[str]] = defaultdict(list)

        for edge in self.edges:
            adjacency[edge.source].append(edge.target)
            in_degree[edge.target] += 1

        queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
        result = []

        while queue:
            node_id = queue.popleft()
            result.append(node_id)
            for neighbor in adjacency[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(self.nodes):
            raise ValueError("DAG contains a cycle")

        return result

    def get_ready_nodes(self) -> List[str]:
        """Return node IDs whose dependencies are all completed."""
        ready = []
        for node_id, node in self.nodes.items():
            if node.status != NodeStatus.PENDING:
                continue
            all_deps_done = all(
                self.nodes[dep].status in (NodeStatus.COMPLETED, NodeStatus.SKIPPED)
                for dep in node.dependencies
                if dep in self.nodes
            )
            if all_deps_done:
                ready.append(node_id)
        return ready

    def validate_dag(self) -> List[str]:
        """Check for cycles, missing dependencies, and other issues."""
        issues = []

        # Check for missing dependency references
        for node_id, node in self.nodes.items():
            for dep in node.dependencies:
                if dep not in self.nodes:
                    issues.append(f"Node '{node_id}' depends on missing node '{dep}'")

        # Check for cycles
        try:
            self.topological_sort()
        except ValueError:
            issues.append("DAG contains a cycle")

        # Check edges reference valid nodes
        for edge in self.edges:
            if edge.source not in self.nodes:
                issues.append(f"Edge source '{edge.source}' not found in nodes")
            if edge.target not in self.nodes:
                issues.append(f"Edge target '{edge.target}' not found in nodes")

        return issues

    def get_parallel_groups(self) -> List[List[str]]:
        """
        Return groups of nodes that can run in parallel.

        Uses topological layering: nodes in the same layer have all
        dependencies satisfied by previous layers.
        """
        layers = self._compute_layers()
        return [layer for layer in layers if len(layer) > 1]

    def _compute_layers(self) -> List[List[str]]:
        """Compute topological layers for layout."""
        if not self.nodes:
            return []

        # Compute longest path from any source to each node
        topo_order = self.topological_sort()
        depth: Dict[str, int] = {}

        for node_id in topo_order:
            node = self.nodes[node_id]
            if not node.dependencies:
                depth[node_id] = 0
            else:
                depth[node_id] = max(
                    depth.get(dep, 0) for dep in node.dependencies if dep in self.nodes
                ) + 1

        # Group by depth
        max_depth = max(depth.values()) if depth else 0
        layers: List[List[str]] = [[] for _ in range(max_depth + 1)]
        for node_id, d in depth.items():
            layers[d].append(node_id)

        return layers

    def to_layout(self) -> Dict[str, Any]:
        """
        Compute x,y positions for each node for visualization.

        Returns dict with 'nodes' (id -> {x, y, ...}) and 'edges'.
        Layout is left-to-right with parallel nodes stacked vertically.
        """
        layers = self._compute_layers()

        LAYER_SPACING = 220
        NODE_SPACING = 120
        PADDING_X = 80
        PADDING_Y = 60

        node_positions: Dict[str, Dict[str, Any]] = {}

        for layer_idx, layer in enumerate(layers):
            x = PADDING_X + layer_idx * LAYER_SPACING
            total_height = (len(layer) - 1) * NODE_SPACING
            start_y = PADDING_Y + (400 - total_height) / 2  # Center vertically

            for node_idx, node_id in enumerate(layer):
                y = start_y + node_idx * NODE_SPACING
                node = self.nodes[node_id]
                node_positions[node_id] = {
                    **node.to_dict(),
                    "x": x,
                    "y": y,
                    "layer": layer_idx,
                }

        edge_list = [edge.to_dict() for edge in self.edges]

        return {
            "nodes": node_positions,
            "edges": edge_list,
            "layers": [[nid for nid in layer] for layer in layers],
            "width": PADDING_X * 2 + max(0, len(layers) - 1) * LAYER_SPACING + 160,
            "height": PADDING_Y * 2 + 400,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the entire DAG definition."""
        return {
            "nodes": {nid: node.to_dict() for nid, node in self.nodes.items()},
            "edges": [edge.to_dict() for edge in self.edges],
        }

    def mark_node(self, node_id: str, status: str, progress_pct: float = 0.0) -> None:
        """Update a node's status and progress."""
        if node_id in self.nodes:
            self.nodes[node_id].status = status
            self.nodes[node_id].progress_pct = progress_pct

    def reset(self) -> None:
        """Reset all nodes to pending."""
        for node in self.nodes.values():
            node.status = NodeStatus.PENDING
            node.progress_pct = 0.0
