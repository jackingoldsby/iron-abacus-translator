import React, { useState } from 'react';
import './PrefectVisualization.css';

/**
 * PrefectVisualization Component
 *
 * Embeds Prefect UI for flow visualization via backend proxy.
 * Shows the flow run graph, tasks, and execution details.
 *
 * Props:
 * - flowRunId: The Prefect flow run ID to visualize
 * - height: iframe height in pixels (default: 600)
 */
function PrefectVisualization({ flowRunId, height = 600 }) {
  const [view, setView] = useState('graph'); // 'graph', 'logs', 'details'

  if (!flowRunId) {
    return (
      <div className="prefect-visualization empty">
        <p>No workflow selected</p>
      </div>
    );
  }

  const getPrefectUrl = () => {
    const baseUrl = `/api/workflow/prefect-ui/flow-runs/flow-run/${flowRunId}`;

    switch (view) {
      case 'graph':
        return `${baseUrl}?tab=graph`;
      case 'logs':
        return `${baseUrl}?tab=logs`;
      case 'details':
        return baseUrl;
      default:
        return `${baseUrl}?tab=graph`;
    }
  };

  return (
    <div className="prefect-visualization">
      <div className="prefect-header">
        <div className="prefect-title">
          🌊 Prefect Flow Visualization
        </div>
        <div className="prefect-tabs">
          <button
            className={`prefect-tab ${view === 'graph' ? 'active' : ''}`}
            onClick={() => setView('graph')}
          >
            📊 Graph
          </button>
          <button
            className={`prefect-tab ${view === 'logs' ? 'active' : ''}`}
            onClick={() => setView('logs')}
          >
            📝 Logs
          </button>
          <button
            className={`prefect-tab ${view === 'details' ? 'active' : ''}`}
            onClick={() => setView('details')}
          >
            ℹ️ Details
          </button>
          <a
            href={`http://localhost:4200/flow-runs/flow-run/${flowRunId}`}
            target="_blank"
            rel="noopener noreferrer"
            className="prefect-external-link"
            title="Open in Prefect UI (new tab)"
          >
            🔗 Open in Prefect
          </a>
        </div>
      </div>

      <div className="prefect-iframe-container" style={{ height: `${height}px` }}>
        <iframe
          src={getPrefectUrl()}
          title="Prefect Flow Visualization"
          className="prefect-iframe"
          sandbox="allow-same-origin allow-scripts allow-popups allow-forms"
        />
      </div>

      <div className="prefect-footer">
        <span className="prefect-info">
          Flow Run ID: <code>{flowRunId}</code>
        </span>
      </div>
    </div>
  );
}

export default PrefectVisualization;
