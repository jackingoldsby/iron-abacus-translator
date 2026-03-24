import React, { useCallback, useMemo, useState, useEffect, useRef } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from 'dagre';
import './DAGVisualization.css';

// =============================================================================
// ICON MAP
// =============================================================================

const ICONS = {
  folder: '\uD83D\uDCC2',
  tag: '\uD83C\uDFF7\uFE0F',
  list: '\uD83D\uDCCB',
  heading: '\uD83D\uDCC4',
  book: '\uD83D\uDCD6',
  shield: '\uD83D\uDEE1\uFE0F',
  'shield-check': '\u2705',
  star: '\u2B50',
  'user-x': '\uD83D\uDEAB',
  filter: '\uD83D\uDD0D',
  'chart-bar': '\uD83D\uDCCA',
  'check-circle': '\u2714\uFE0F',
  'book-open': '\uD83D\uDCD6',
  eraser: '\uD83E\uDDF9',
};

// =============================================================================
// STATUS COLORS (matches StageNode.jsx)
// =============================================================================

const STATUS_COLORS = {
  pending:   { border: '#bdbdbd', bg: '#fafafa',  text: '#999' },
  ready:     { border: '#42a5f5', bg: '#e3f2fd',  text: '#1976d2' },
  running:   { border: '#2196f3', bg: '#e3f2fd',  text: '#1565c0' },
  completed: { border: '#4caf50', bg: '#e8f5e9',  text: '#2e7d32' },
  failed:    { border: '#f44336', bg: '#ffebee',  text: '#c62828' },
  skipped:   { border: '#ff9800', bg: '#fff3e0',  text: '#e65100' },
};

const STATUS_LABELS = {
  pending: '\u25CB',
  ready: '\u25CE',
  running: '\u25CF',
  completed: '\u2713',
  failed: '\u2717',
  skipped: '\u2298',
};

// =============================================================================
// CUSTOM NODE COMPONENT
// =============================================================================

function TaskNode({ data, selected }) {
  const status = data.status || 'pending';
  const colors = STATUS_COLORS[status] || STATUS_COLORS.pending;
  const isQualityGate = data.node_type === 'quality_gate';

  return (
    <div
      className={`dag-node status-${status} ${isQualityGate ? 'quality-gate' : ''} ${selected ? 'selected' : ''}`}
      style={{ borderColor: colors.border, background: colors.bg }}
    >
      <div className="dag-node-header">
        <span className="dag-node-icon">
          {ICONS[data.metadata?.icon] || '\u2B1B'}
        </span>
        <span className="dag-node-name">{data.display_name}</span>
      </div>

      <div className="dag-node-status" style={{ color: colors.text }}>
        {STATUS_LABELS[status]} {status}
      </div>

      {isQualityGate && (
        <div className="dag-node-gate-badge">Quality Gate</div>
      )}

      {status === 'running' && data.progress_pct > 0 && (
        <div className="dag-node-progress">
          <div className="dag-node-progress-bar">
            <div
              className="dag-node-progress-fill"
              style={{
                width: `${data.progress_pct}%`,
                background: colors.border,
              }}
            />
          </div>
          <div className="dag-node-progress-text">
            {data.progress_pct.toFixed(0)}%
          </div>
        </div>
      )}

      {status === 'completed' && data.duration_seconds && (
        <div className="dag-node-metrics">
          <span className="dag-node-metric">
            \u23F1 {formatDuration(data.duration_seconds)}
          </span>
        </div>
      )}
    </div>
  );
}

function formatDuration(seconds) {
  if (!seconds) return '';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

// Register custom node types
const nodeTypes = { taskNode: TaskNode };

// =============================================================================
// DAGRE LAYOUT
// =============================================================================

function getLayoutedElements(dagData, direction = 'LR') {
  if (!dagData?.nodes || !dagData?.edges) return { nodes: [], edges: [] };

  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({
    rankdir: direction,
    nodesep: 60,
    ranksep: 100,
    marginx: 40,
    marginy: 40,
  });

  const nodeWidth = 190;
  const nodeHeight = 90;

  // Add nodes to dagre
  const nodeEntries = Object.entries(dagData.nodes);
  for (const [id, node] of nodeEntries) {
    dagreGraph.setNode(id, { width: nodeWidth, height: nodeHeight });
  }

  // Add edges to dagre
  for (const edge of dagData.edges) {
    dagreGraph.setEdge(edge.source, edge.target);
  }

  dagre.layout(dagreGraph);

  // Convert to ReactFlow format
  const nodes = nodeEntries.map(([id, nodeData]) => {
    const pos = dagreGraph.node(id);
    return {
      id,
      type: 'taskNode',
      position: { x: pos.x - nodeWidth / 2, y: pos.y - nodeHeight / 2 },
      data: { ...nodeData },
    };
  });

  const edges = dagData.edges.map((edge, i) => {
    const isQualityGate = edge.edge_type === 'quality_gate';
    const sourceStatus = dagData.nodes[edge.source]?.status;
    const edgeColor = STATUS_COLORS[sourceStatus]?.border || '#bdbdbd';

    return {
      id: `e-${edge.source}-${edge.target}`,
      source: edge.source,
      target: edge.target,
      type: 'smoothstep',
      animated: sourceStatus === 'running',
      style: {
        stroke: edgeColor,
        strokeWidth: isQualityGate ? 3 : 2,
        strokeDasharray: isQualityGate ? '8 4' : undefined,
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: edgeColor,
        width: 16,
        height: 16,
      },
    };
  });

  return { nodes, edges };
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export default function DAGVisualization({
  dagData,
  nodeStatuses,
  onNodeClick,
  onNodeAction,
  direction = 'LR',
}) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [contextMenu, setContextMenu] = useState(null);
  const contextMenuRef = useRef(null);

  // Merge live statuses into DAG data
  const mergedDagData = useMemo(() => {
    if (!dagData) return null;
    const merged = { ...dagData, nodes: { ...dagData.nodes } };
    if (nodeStatuses) {
      for (const [nodeId, statusInfo] of Object.entries(nodeStatuses)) {
        if (merged.nodes[nodeId]) {
          merged.nodes[nodeId] = {
            ...merged.nodes[nodeId],
            status: statusInfo.status,
            progress_pct: statusInfo.progress_pct || 0,
            duration_seconds: statusInfo.duration_seconds,
          };
        }
      }
    }
    return merged;
  }, [dagData, nodeStatuses]);

  // Layout with dagre
  useEffect(() => {
    if (!mergedDagData) return;
    const { nodes: layoutNodes, edges: layoutEdges } = getLayoutedElements(
      mergedDagData,
      direction
    );
    setNodes(layoutNodes);
    setEdges(layoutEdges);
  }, [mergedDagData, direction, setNodes, setEdges]);

  const handleNodeClick = useCallback(
    (event, node) => {
      if (onNodeClick) onNodeClick(node.id, node.data);
    },
    [onNodeClick]
  );

  const handleNodeContextMenu = useCallback(
    (event, node) => {
      event.preventDefault();
      setContextMenu({
        x: event.clientX,
        y: event.clientY,
        nodeId: node.id,
        nodeData: node.data,
      });
    },
    []
  );

  const handlePaneClick = useCallback(() => {
    setContextMenu(null);
  }, []);

  // Close context menu on outside click
  useEffect(() => {
    const handler = (e) => {
      if (contextMenuRef.current && !contextMenuRef.current.contains(e.target)) {
        setContextMenu(null);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleContextAction = useCallback(
    (action) => {
      if (contextMenu && onNodeAction) {
        onNodeAction(action, contextMenu.nodeId);
      }
      setContextMenu(null);
    },
    [contextMenu, onNodeAction]
  );

  if (!dagData) {
    return <div className="dag-loading">Loading pipeline...</div>;
  }

  return (
    <div className="dag-visualization">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        onNodeContextMenu={handleNodeContextMenu}
        onPaneClick={handlePaneClick}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.3}
        maxZoom={2}
        nodesDraggable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#e0e0e0" gap={20} />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(node) => {
            const s = node.data?.status || 'pending';
            return STATUS_COLORS[s]?.border || '#bdbdbd';
          }}
          maskColor="rgba(0,0,0,0.08)"
          style={{ border: '1px solid #ddd', borderRadius: 4 }}
        />
      </ReactFlow>

      {/* Context Menu */}
      {contextMenu && (
        <div
          ref={contextMenuRef}
          className="dag-context-menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <div
            className="dag-context-menu-item"
            onClick={() => handleContextAction('retry')}
          >
            \u21BB Retry Node
          </div>
          <div
            className="dag-context-menu-item"
            onClick={() => handleContextAction('skip')}
          >
            \u23ED Skip Node
          </div>
          {contextMenu.nodeData?.node_type === 'quality_gate' && (
            <div
              className="dag-context-menu-item"
              onClick={() => handleContextAction('validate')}
            >
              \u2714 Validate (Force Pass)
            </div>
          )}
          <div className="dag-context-menu-divider" />
          <div
            className="dag-context-menu-item"
            onClick={() => handleContextAction('view_logs')}
          >
            \uD83D\uDCCB View Logs
          </div>
        </div>
      )}
    </div>
  );
}
