import React, { useState, useEffect, useCallback, useRef } from 'react';
import { workflowAPI } from '../api/client';
import StageNode from './StageNode';
import DrillDownPanel from './DrillDownPanel';

/**
 * WorkflowProgress Component
 *
 * Displays real-time workflow progress with DAG visualization
 * Features:
 * - Real-time updates via props (SSE managed by parent)
 * - Stage nodes with visual indicators (✓/✗/⏳/progress)
 * - Click to drill-down into logs/validation reports
 * - Overall progress tracking
 *
 * Memoized to prevent unnecessary re-renders when props haven't changed
 */
const WorkflowProgress = React.memo(({ flowRunId, workflowStatus, onComplete }) => {
  const [selectedStage, setSelectedStage] = useState(null);
  const [error, setError] = useState(null);

  // Check if workflow is complete
  useEffect(() => {
    if (workflowStatus && ['completed', 'failed', 'cancelled'].includes(workflowStatus.status) && onComplete) {
      onComplete(workflowStatus);
    }
  }, [workflowStatus?.status, onComplete]);

  // Handle stage click for drill-down
  const handleStageClick = (stage) => {
    setSelectedStage(stage);
  };

  // Close drill-down panel
  const handleCloseDrillDown = () => {
    setSelectedStage(null);
  };

  if (!workflowStatus) {
    return (
      <div className="workflow-progress loading">
        <div className="loading-spinner"></div>
        <p>Loading workflow...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="workflow-progress error">
        <div className="error-icon">✗</div>
        <h3>Error Loading Workflow</h3>
        <p>{error}</p>
        <button onClick={fetchStatus}>Retry</button>
      </div>
    );
  }

  if (!workflowStatus) {
    return (
      <div className="workflow-progress empty">
        <p>No workflow data available</p>
      </div>
    );
  }

  const { work_id, volume, status, overall_progress_pct, current_stage, stages, duration_seconds } = workflowStatus;

  // Format duration
  const formatDuration = (seconds) => {
    if (!seconds) return '0s';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
  };

  // Get status icon and color
  const getStatusDisplay = (status) => {
    const displays = {
      pending: { icon: '⊙', color: '#999', text: 'Pending' },
      scheduled: { icon: '⊙', color: '#999', text: 'Scheduled' },
      running: { icon: '●', color: '#2196F3', text: 'Running' },
      completed: { icon: '✓', color: '#4CAF50', text: 'Completed' },
      failed: { icon: '✗', color: '#f44336', text: 'Failed' },
      cancelled: { icon: '⊘', color: '#FF9800', text: 'Cancelled' },
    };
    return displays[status] || displays.pending;
  };

  const statusDisplay = getStatusDisplay(status);

  return (
    <div className="workflow-progress">
      {/* Header */}
      <div className="workflow-header">
        <div className="workflow-title">
          <h2>
            <span className="status-icon" style={{ color: statusDisplay.color }}>
              {statusDisplay.icon}
            </span>
            Translation Workflow: {work_id}
            {volume && ` (Vol. ${volume})`}
          </h2>
          <span className={`status-badge status-${status}`}>
            {statusDisplay.text}
          </span>
        </div>

        <div className="workflow-meta">
          <div className="meta-item">
            <span className="meta-label">Progress:</span>
            <span className="meta-value">{overall_progress_pct.toFixed(1)}%</span>
          </div>
          {current_stage && (
            <div className="meta-item">
              <span className="meta-label">Current Stage:</span>
              <span className="meta-value">{current_stage}</span>
            </div>
          )}
          <div className="meta-item">
            <span className="meta-label">Duration:</span>
            <span className="meta-value">{formatDuration(duration_seconds)}</span>
          </div>
        </div>
      </div>

      {/* Overall Progress Bar */}
      <div className="overall-progress">
        <div className="progress-bar-container">
          <div
            className="progress-bar-fill"
            style={{
              width: `${overall_progress_pct}%`,
              backgroundColor: statusDisplay.color
            }}
          />
        </div>
        <span className="progress-label">{overall_progress_pct.toFixed(1)}%</span>
      </div>

      {/* Stage Nodes (DAG-style) */}
      <div className="workflow-stages">
        <div className="stages-container">
          {stages && stages.length > 0 ? (
            stages.map((stage, index) => (
              <React.Fragment key={stage.stage_name}>
                <StageNode
                  stage={stage}
                  onClick={() => handleStageClick(stage)}
                  isSelected={selectedStage?.stage_name === stage.stage_name}
                />
                {/* Arrow connector between stages */}
                {index < stages.length - 1 && (
                  <div className="stage-connector">→</div>
                )}
              </React.Fragment>
            ))
          ) : (
            <div className="no-stages">
              <p>No stages available yet</p>
            </div>
          )}
        </div>
      </div>

      {/* Drill-down Panel */}
      {selectedStage && (
        <DrillDownPanel
          stage={selectedStage}
          flowRunId={flowRunId}
          onClose={handleCloseDrillDown}
        />
      )}
    </div>
  );
}, (prevProps, nextProps) => {
  // Custom comparison: only re-render if these props actually changed
  const flowRunIdEqual = prevProps.flowRunId === nextProps.flowRunId;
  const workflowStatusEqual = JSON.stringify(prevProps.workflowStatus) === JSON.stringify(nextProps.workflowStatus);

  // Return true to SKIP re-render, false to re-render
  return flowRunIdEqual && workflowStatusEqual;
});

export default WorkflowProgress;
