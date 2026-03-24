import React, { useState, useEffect } from 'react';
import { workflowAPI } from '../api/client';
import './StartWorkflowModal.css';

/**
 * StartWorkflowModal Component
 *
 * Modal dialog for starting a new translation workflow.
 * Replaces native browser prompt() with a proper form interface.
 */
function StartWorkflowModal({ isOpen, onClose, onSubmit }) {
  const [workId, setWorkId] = useState('');
  const [volume, setVolume] = useState('');
  const [workflowId, setWorkflowId] = useState('');
  const [workflows, setWorkflows] = useState([]);
  const [loadingWorkflows, setLoadingWorkflows] = useState(false);
  const [errors, setErrors] = useState({});

  // Load workflows when modal opens
  useEffect(() => {
    if (isOpen) {
      setWorkId('');
      setVolume('');
      setWorkflowId('');
      setErrors({});
      loadWorkflows();
    }
  }, [isOpen]);

  const loadWorkflows = async () => {
    setLoadingWorkflows(true);
    try {
      const data = await workflowAPI.listTemplates();
      setWorkflows(data.templates || []);
      // Auto-select first workflow if available
      if (data.templates && data.templates.length > 0) {
        setWorkflowId(data.templates[0].workflow_id);
      }
    } catch (error) {
      console.error('Failed to load workflows:', error);
      setErrors({ ...errors, workflows: 'Failed to load workflows' });
    } finally {
      setLoadingWorkflows(false);
    }
  };

  const validateForm = () => {
    const newErrors = {};

    // Workflow validation
    if (!workflowId) {
      newErrors.workflowId = 'Please select a workflow';
    }

    // Work ID validation
    if (!workId.trim()) {
      newErrors.workId = 'Work ID is required';
    } else if (!/^[A-Za-z0-9]+$/.test(workId.trim())) {
      newErrors.workId = 'Work ID must be alphanumeric (e.g., D1379, I1046)';
    }

    // Volume validation (optional, but must be single letter if provided)
    if (volume && !/^[a-zA-Z]$/.test(volume)) {
      newErrors.volume = 'Volume must be a single letter (e.g., a, b, c)';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = (e) => {
    e.preventDefault();

    if (!validateForm()) {
      return;
    }

    // Call onSubmit with cleaned values
    const selectedWorkflow = workflows.find(w => w.workflow_id === workflowId);
    onSubmit({
      workflowId: workflowId,
      workflowName: selectedWorkflow?.name || 'Unknown Workflow',
      workId: workId.trim(),
      volume: volume.trim() || null
    });

    // Close modal
    onClose();
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      onClose();
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-content"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <div className="modal-header">
          <h2>⚡ Start New Workflow</h2>
          <button
            type="button"
            className="modal-close"
            onClick={onClose}
            aria-label="Close modal"
          >
            ×
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {/* Workflow Selection */}
            <div className="form-group">
              <label htmlFor="workflow">
                Workflow <span className="required">*</span>
              </label>
              {loadingWorkflows ? (
                <div className="loading-message">Loading workflows...</div>
              ) : (
                <select
                  id="workflow"
                  className={`form-control ${errors.workflowId ? 'error' : ''}`}
                  value={workflowId}
                  onChange={(e) => setWorkflowId(e.target.value)}
                  disabled={workflows.length === 0}
                >
                  {workflows.length === 0 ? (
                    <option value="">No workflows available</option>
                  ) : (
                    workflows.map((workflow) => (
                      <option key={workflow.workflow_id} value={workflow.workflow_id}>
                        {workflow.name} ({workflow.stages.length} stages)
                      </option>
                    ))
                  )}
                </select>
              )}
              {errors.workflowId && (
                <span className="error-message">{errors.workflowId}</span>
              )}
              {workflowId && workflows.find(w => w.workflow_id === workflowId) && (
                <span className="form-help">
                  {workflows.find(w => w.workflow_id === workflowId).description}
                </span>
              )}
            </div>

            {/* Work ID Field */}
            <div className="form-group">
              <label htmlFor="work-id">
                Work ID <span className="required">*</span>
              </label>
              <input
                id="work-id"
                type="text"
                className={`form-control ${errors.workId ? 'error' : ''}`}
                placeholder="e.g., D1379, I1046"
                value={workId}
                onChange={(e) => setWorkId(e.target.value)}
                autoFocus
              />
              {errors.workId && (
                <span className="error-message">{errors.workId}</span>
              )}
              <span className="form-help">
                Enter the work identifier from the catalog
              </span>
            </div>

            {/* Volume Field */}
            <div className="form-group">
              <label htmlFor="volume">Volume (Optional)</label>
              <input
                id="volume"
                type="text"
                className={`form-control ${errors.volume ? 'error' : ''}`}
                placeholder="e.g., a, b, c"
                value={volume}
                onChange={(e) => setVolume(e.target.value)}
                maxLength="1"
              />
              {errors.volume && (
                <span className="error-message">{errors.volume}</span>
              )}
              <span className="form-help">
                Leave blank to translate all volumes
              </span>
            </div>
          </div>

          <div className="modal-footer">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={onClose}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-success"
              disabled={!workId.trim() || !workflowId || loadingWorkflows}
            >
              ⚡ Start Workflow
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default StartWorkflowModal;
