import React, { useState, useEffect } from 'react';
import { workflowAPI } from '../api/client';
import { showToast } from '../components/Toast';
import './WorkflowsPage.css';

/**
 * WorkflowsPage Component
 *
 * Browse and view workflow templates.
 * Shows template details, stages, and configuration options.
 */
function WorkflowsPage() {
  const [workflows, setWorkflows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedWorkflow, setSelectedWorkflow] = useState(null);

  useEffect(() => {
    loadWorkflows();
  }, []);

  const loadWorkflows = async () => {
    setLoading(true);
    try {
      const data = await workflowAPI.listTemplates();
      setWorkflows(data.templates || []);

      // Auto-select first workflow if available
      if (data.templates && data.templates.length > 0 && !selectedWorkflow) {
        setSelectedWorkflow(data.templates[0]);
      }
    } catch (error) {
      console.error('Failed to load workflows:', error);
      showToast('error', 'Failed to load workflows');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="workflows-page">
        <div className="loading-container">
          <div className="spinner"></div>
          <p>Loading workflows...</p>
        </div>
      </div>
    );
  }

  if (workflows.length === 0) {
    return (
      <div className="workflows-page">
        <div className="empty-state">
          <h2>No Workflows Available</h2>
          <p>No workflow templates are currently configured.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="workflows-page">
      <div className="page-header">
        <h1>⚙️ Workflow Templates</h1>
        <p>Browse and view available translation workflow templates</p>
      </div>

      <div className="workflows-layout">
        {/* Workflow List */}
        <div className="workflow-list">
          <h2>Templates ({workflows.length})</h2>
          <div className="workflow-cards">
            {workflows.map((workflow) => (
              <div
                key={workflow.workflow_id}
                className={`workflow-card ${selectedWorkflow?.workflow_id === workflow.workflow_id ? 'selected' : ''}`}
                onClick={() => setSelectedWorkflow(workflow)}
              >
                <div className="workflow-card-header">
                  <h3>{workflow.name}</h3>
                  <span className="workflow-id">{workflow.workflow_id}</span>
                </div>
                <p className="workflow-description">{workflow.description}</p>
                <div className="workflow-meta">
                  <span className="stage-count">
                    {workflow.stages.length} stages
                  </span>
                  {workflow.is_system_template && (
                    <span className="system-badge">System</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Workflow Details */}
        {selectedWorkflow && (
          <div className="workflow-details">
            <div className="details-header">
              <h2>{selectedWorkflow.name}</h2>
              <div className="header-badges">
                {selectedWorkflow.is_system_template && (
                  <span className="badge badge-system">System Template</span>
                )}
                {!selectedWorkflow.is_editable && (
                  <span className="badge badge-readonly">Read-only</span>
                )}
              </div>
            </div>

            <div className="details-section">
              <h3>Description</h3>
              <p>{selectedWorkflow.description}</p>
            </div>

            <div className="details-section">
              <h3>Template Information</h3>
              <table className="info-table">
                <tbody>
                  <tr>
                    <td className="label">Workflow ID:</td>
                    <td><code>{selectedWorkflow.workflow_id}</code></td>
                  </tr>
                  <tr>
                    <td className="label">Version:</td>
                    <td>{selectedWorkflow.version}</td>
                  </tr>
                  <tr>
                    <td className="label">Stages:</td>
                    <td>{selectedWorkflow.stages.length}</td>
                  </tr>
                  <tr>
                    <td className="label">Created:</td>
                    <td>{new Date(selectedWorkflow.created_at).toLocaleDateString()}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="details-section">
              <h3>Pipeline Stages</h3>
              <div className="stages-list">
                {selectedWorkflow.stages.map((stage) => (
                  <div key={stage.number} className="stage-item">
                    <div className="stage-header">
                      <span className="stage-icon">{stage.icon}</span>
                      <span className="stage-number">Stage {stage.number}</span>
                      <span className="stage-name">{stage.display_name}</span>
                      {stage.is_parallel && (
                        <span className="parallel-badge">Parallel</span>
                      )}
                    </div>
                    <p className="stage-description">{stage.description}</p>
                    {stage.requires_footnotes && (
                      <span className="footnote-badge">✨ Generates footnotes</span>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div className="details-section">
              <h3>Default Configuration</h3>
              <pre className="config-block">
                {JSON.stringify(selectedWorkflow.default_config, null, 2)}
              </pre>
            </div>

            {selectedWorkflow.run_count > 0 && (
              <div className="details-section">
                <h3>Statistics</h3>
                <div className="stats-grid">
                  <div className="stat-card">
                    <div className="stat-value">{selectedWorkflow.run_count}</div>
                    <div className="stat-label">Total Runs</div>
                  </div>
                  <div className="stat-card">
                    <div className="stat-value">{selectedWorkflow.success_rate.toFixed(1)}%</div>
                    <div className="stat-label">Success Rate</div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default WorkflowsPage;
