import React, { useState, useEffect, useRef } from 'react';
import { workflowAPI } from '../api/client';
import { showToast } from './Toast';
import './WorkflowControls.css';

/**
 * WorkflowControls Component
 *
 * Bottom control panel for workflow management displaying:
 * - Overall progress percentage and stats
 * - Time elapsed/estimated
 * - Current stage and status
 * - Error/warning counts
 * - Control buttons: Pause/Resume, Cancel, Rollback, Delete Stage, Delete All
 *
 * Props:
 * - flowRunId: The workflow run ID
 * - onPause: Callback for pause action
 * - onResume: Callback for resume action
 * - onCancel: Callback for cancel action
 * - onRollback: Callback for rollback action
 * - onDeleteStage: Callback for stage deletion
 * - onDeleteAll: Callback for deleting all results
 */
function WorkflowControls({
  flowRunId,
  workflowStatus,
  onPause,
  onResume,
  onCancel,
  onRollback,
  onDeleteStage,
  onDeleteAll
}) {
  // Manual refresh function for refresh button
  const loadWorkflowStatus = async () => {
    try {
      const status = await workflowAPI.getStatus(flowRunId);
      // Note: This won't update the parent's state, but provides feedback
      // Parent's SSE connection will eventually sync
      showToast('Workflow status refreshed', 'info', 2000);
    } catch (error) {
      console.error('Failed to load workflow status:', error);
      showToast('Failed to refresh status', 'error');
    }
  };

  const handleCancel = async () => {
    if (!confirm('Are you sure you want to cancel this workflow? This action cannot be undone.')) {
      return;
    }

    try {
      await workflowAPI.cancel(flowRunId);
      showToast('Workflow cancelled successfully', 'success');
      if (onCancel) onCancel();
    } catch (error) {
      console.error('Failed to cancel workflow:', error);
      showToast(`Failed to cancel workflow: ${error.message}`, 'error');
    }
  };

  const handlePause = async () => {
    try {
      await workflowAPI.pause(flowRunId);
      showToast('Workflow paused successfully', 'success');
      loadWorkflowStatus(); // Refresh to update button state
      if (onPause) onPause();
    } catch (error) {
      console.error('Failed to pause workflow:', error);
      showToast(`Failed to pause workflow: ${error.response?.data?.detail || error.message}`, 'error');
    }
  };

  const handleResume = async () => {
    try {
      await workflowAPI.resume(flowRunId);
      showToast('Workflow resumed successfully', 'success');
      loadWorkflowStatus(); // Refresh to update button state
      if (onResume) onResume();
    } catch (error) {
      console.error('Failed to resume workflow:', error);
      showToast(`Failed to resume workflow: ${error.response?.data?.detail || error.message}`, 'error');
    }
  };

  const handleRollback = async () => {
    const stage = prompt('Enter stage number to rollback to (1-7):\n\n1. BODY\n2. METADATA\n3. TOC\n4. HEADINGS\n5. SPECIAL\n6. CLEANUP\n7. VALIDATION');

    if (!stage || isNaN(stage)) {
      return;
    }

    const targetStage = parseInt(stage);
    if (targetStage < 1 || targetStage > 7) {
      showToast('Stage number must be between 1 and 7', 'error');
      return;
    }

    if (!confirm(`Rollback to Stage ${targetStage}?\n\nThis will DELETE all WIP files and logs for stages ${targetStage + 1}-7.\n\nThis action cannot be undone!`)) {
      return;
    }

    try {
      const result = await workflowAPI.rollback(flowRunId, targetStage);
      showToast(
        `Rolled back to stage ${targetStage}. Deleted ${result.total_files_deleted} files from ${result.deleted_stages.length} stages.`,
        'success',
        6000
      );
      loadWorkflowStatus(); // Refresh to update UI
      if (onRollback) onRollback(targetStage);
    } catch (error) {
      console.error('Failed to rollback workflow:', error);
      showToast(`Failed to rollback: ${error.response?.data?.detail || error.message}`, 'error');
    }
  };

  const handleDeleteStage = async () => {
    const stage = prompt('Enter stage number to delete results for (1-7):\n\n1. BODY\n2. METADATA\n3. TOC\n4. HEADINGS\n5. SPECIAL\n6. CLEANUP\n7. VALIDATION');

    if (!stage || isNaN(stage)) {
      return;
    }

    const stageNum = parseInt(stage);
    if (stageNum < 1 || stageNum > 7) {
      showToast('Stage number must be between 1 and 7', 'error');
      return;
    }

    if (!confirm(`Delete results for Stage ${stageNum}?\n\nThis will DELETE all WIP files and logs for this stage.\n\nThis action cannot be undone!`)) {
      return;
    }

    try {
      const result = await workflowAPI.deleteStage(flowRunId, stageNum);
      showToast(
        `Deleted stage ${stageNum} results. Removed ${result.total_files_deleted} files.`,
        'success',
        6000
      );
      loadWorkflowStatus(); // Refresh to update UI
      if (onDeleteStage) onDeleteStage(stageNum);
    } catch (error) {
      console.error('Failed to delete stage:', error);
      showToast(`Failed to delete stage: ${error.response?.data?.detail || error.message}`, 'error');
    }
  };

  const handleDeleteAll = async () => {
    if (!confirm('Delete ALL workflow results?\n\nThis will remove all WIP files and logs for ALL stages.\n\nThis action cannot be undone!')) {
      return;
    }

    try {
      const result = await workflowAPI.deleteAll(flowRunId);
      showToast(
        `Deleted all results. Removed ${result.total_files_deleted} files from ${result.deleted_stages.length} stages.`,
        'success',
        6000
      );
      loadWorkflowStatus(); // Refresh to update UI
      if (onDeleteAll) onDeleteAll();
    } catch (error) {
      console.error('Failed to delete all results:', error);
      showToast(`Failed to delete all: ${error.response?.data?.detail || error.message}`, 'error');
    }
  };

  if (!workflowStatus) {
    return (
      <div className="workflow-controls loading">
        <div className="spinner"></div>
      </div>
    );
  }

  const isRunning = workflowStatus.status === 'running';
  const isPaused = workflowStatus.status === 'paused';
  const isCompleted = workflowStatus.status === 'completed';
  const isFailed = workflowStatus.status === 'failed';
  const canPause = isRunning && onPause;
  const canResume = isPaused && onResume;

  const completedStages = workflowStatus.stages?.filter(s => s.status === 'completed').length || 0;
  const totalStages = 7;
  const errorCount = workflowStatus.stages?.reduce((sum, s) => sum + s.error_count, 0) || 0;
  const warningCount = 0; // TODO: Add warning tracking

  return (
    <div className="workflow-controls">
      {/* Progress Summary */}
      <div className="controls-section progress-summary">
        <h3>Overall Progress</h3>
        <div className="progress-bar-large">
          <div
            className="progress-fill-large"
            style={{
              width: `${workflowStatus.overall_progress_pct}%`,
              background: getProgressColor(workflowStatus.overall_progress_pct, workflowStatus.status)
            }}
          >
            <span className="progress-percentage">
              {workflowStatus.overall_progress_pct.toFixed(1)}%
            </span>
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="controls-section stats-section">
        <div className="stat-item">
          <div className="stat-label">Stages</div>
          <div className="stat-value">
            {completedStages}/{totalStages}
          </div>
        </div>
        <div className="stat-item">
          <div className="stat-label">Current Stage</div>
          <div className="stat-value">
            {workflowStatus.current_stage || 'N/A'}
          </div>
        </div>
        <div className="stat-item">
          <div className="stat-label">Time Elapsed</div>
          <div className="stat-value">
            {formatDuration(workflowStatus.duration_seconds)}
          </div>
        </div>
        <div className="stat-item">
          <div className="stat-label">Status</div>
          <div className="stat-value">
            <span className={`badge badge-${getStatusColor(workflowStatus.status)}`}>
              {workflowStatus.status}
            </span>
          </div>
        </div>
        {errorCount > 0 && (
          <div className="stat-item error">
            <div className="stat-label">Errors</div>
            <div className="stat-value error-value">
              {errorCount}
            </div>
          </div>
        )}
      </div>

      {/* Control Buttons */}
      <div className="controls-section actions-section">
        <h3>Workflow Controls</h3>
        <div className="action-buttons">
          {canPause && (
            <button
              className="btn btn-warning"
              onClick={handlePause}
              title="Pause workflow"
            >
              ⏸ Pause
            </button>
          )}
          {canResume && (
            <button
              className="btn btn-success"
              onClick={handleResume}
              title="Resume workflow"
            >
              ▶️ Resume
            </button>
          )}
          <button
            className="btn btn-danger"
            onClick={handleCancel}
            disabled={isCompleted}
            title="Cancel workflow"
          >
            ✕ Cancel
          </button>
          <button
            className="btn btn-secondary"
            onClick={handleRollback}
            disabled={isRunning}
            title="Rollback to a previous stage - deletes WIP files and logs for later stages"
          >
            ⏮ Rollback
          </button>
          <button
            className="btn btn-secondary"
            onClick={handleDeleteStage}
            disabled={isRunning}
            title="Delete WIP files and logs for a specific stage"
          >
            🗑 Delete Stage
          </button>
          <button
            className="btn btn-danger"
            onClick={handleDeleteAll}
            disabled={isRunning}
            title="Delete all WIP files and logs for all stages"
          >
            🗑 Delete All
          </button>
          <button
            className="btn btn-secondary"
            onClick={loadWorkflowStatus}
            title="Refresh workflow status"
          >
            🔄 Refresh
          </button>
        </div>

        {/* Controls Info */}
        <div className="phase-notice">
          <p>
            <strong>Advanced Controls:</strong> Pause/Resume, Rollback, and Delete operations are now available.
            All operations cannot be performed while a workflow is running.
          </p>
        </div>
      </div>
    </div>
  );
}

function getProgressColor(percentage, status) {
  if (status === 'failed') return '#e74c3c';
  if (status === 'completed') return '#27ae60';
  if (percentage >= 75) return '#3498db';
  if (percentage >= 50) return '#f39c12';
  return '#95a5a6';
}

function getStatusColor(status) {
  switch (status?.toLowerCase()) {
    case 'completed': return 'success';
    case 'running': return 'warning';
    case 'failed': return 'danger';
    case 'cancelled': return 'secondary';
    case 'pending': return 'info';
    default: return 'secondary';
  }
}

function formatDuration(seconds) {
  if (!seconds) return '-';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  if (hours > 0) {
    return `${hours}h ${minutes}m ${secs}s`;
  } else if (minutes > 0) {
    return `${minutes}m ${secs}s`;
  } else {
    return `${secs}s`;
  }
}

export default WorkflowControls;
