import React, { useState, useEffect } from 'react';
import './StageComparison.css';

/**
 * StageComparison Component
 *
 * Side-by-side comparison of WIP files between two stages.
 * Features:
 * - Visual diff view with highlighting
 * - Summary statistics (size changes, field changes)
 * - Field-level comparison
 * - Expandable sections
 *
 * Props:
 * - flowRunId: The workflow run ID
 * - fromStage: Source stage number
 * - toStage: Target stage number
 * - onClose: Callback to close the comparison view
 */
function StageComparison({ flowRunId, fromStage, toStage, onClose }) {
  const [comparison, setComparison] = useState(null);
  const [fromContent, setFromContent] = useState(null);
  const [toContent, setToContent] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [viewMode, setViewMode] = useState('summary'); // 'summary', 'sidebyside', 'unified'

  useEffect(() => {
    if (flowRunId && fromStage && toStage) {
      loadComparison();
      loadStageContents();
    }
  }, [flowRunId, fromStage, toStage]);

  const loadComparison = async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await fetch(
        `http://localhost:8000/api/workflow/wip/compare/${flowRunId}?from_stage=${fromStage}&to_stage=${toStage}`
      );

      if (!response.ok) {
        throw new Error('Failed to load comparison');
      }

      const data = await response.json();
      setComparison(data);
    } catch (err) {
      console.error('Error loading comparison:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const loadStageContents = async () => {
    try {
      const [fromResp, toResp] = await Promise.all([
        fetch(`http://localhost:8000/api/workflow/wip/stage/${flowRunId}/${fromStage}`),
        fetch(`http://localhost:8000/api/workflow/wip/stage/${flowRunId}/${toStage}`)
      ]);

      if (fromResp.ok && toResp.ok) {
        const [fromData, toData] = await Promise.all([
          fromResp.json(),
          toResp.json()
        ]);
        setFromContent(fromData);
        setToContent(toData);
      }
    } catch (err) {
      console.error('Error loading stage contents:', err);
    }
  };

  const formatBytes = (bytes) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
  };

  const renderSummary = () => {
    if (!comparison) return null;

    const sizeChange = comparison.summary.size_diff;
    const percentChange = ((sizeChange / comparison.summary.from_size) * 100).toFixed(1);

    return (
      <div className="comparison-summary">
        <div className="summary-header">
          <h3>Comparison Summary</h3>
          <div className="stage-labels">
            <span className="stage-label from">
              Stage {fromStage}: {comparison.from_stage_name}
            </span>
            <span className="arrow">→</span>
            <span className="stage-label to">
              Stage {toStage}: {comparison.to_stage_name}
            </span>
          </div>
        </div>

        <div className="summary-stats">
          <div className="stat-card">
            <div className="stat-label">Original Size</div>
            <div className="stat-value">{formatBytes(comparison.summary.from_size)}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">New Size</div>
            <div className="stat-value">{formatBytes(comparison.summary.to_size)}</div>
          </div>
          <div className={`stat-card ${sizeChange >= 0 ? 'positive' : 'negative'}`}>
            <div className="stat-label">Size Change</div>
            <div className="stat-value">
              {sizeChange >= 0 ? '+' : ''}{formatBytes(sizeChange)}
              <span className="percent-change"> ({percentChange}%)</span>
            </div>
          </div>
        </div>

        {comparison.field_comparison && (
          <div className="field-comparison">
            <h4>Field-Level Changes</h4>
            <div className="field-info">
              <strong>Field:</strong> {comparison.field_comparison.field}
            </div>
            <div className="field-info">
              <strong>Changed:</strong>{' '}
              {comparison.field_comparison.changed ? (
                <span className="badge badge-warning">Yes</span>
              ) : (
                <span className="badge badge-success">No</span>
              )}
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderSideBySide = () => {
    if (!fromContent || !toContent) return null;

    return (
      <div className="side-by-side">
        <div className="side-panel">
          <h4>Stage {fromStage}: {comparison?.from_stage_name}</h4>
          <div className="json-content">
            <pre>{JSON.stringify(fromContent, null, 2)}</pre>
          </div>
        </div>
        <div className="side-panel">
          <h4>Stage {toStage}: {comparison?.to_stage_name}</h4>
          <div className="json-content">
            <pre>{JSON.stringify(toContent, null, 2)}</pre>
          </div>
        </div>
      </div>
    );
  };

  const renderUnified = () => {
    if (!fromContent || !toContent) return null;

    // Simple unified view showing both
    return (
      <div className="unified-view">
        <div className="unified-section removed">
          <h4>− Stage {fromStage}: {comparison?.from_stage_name}</h4>
          <pre>{JSON.stringify(fromContent, null, 2)}</pre>
        </div>
        <div className="unified-section added">
          <h4>+ Stage {toStage}: {comparison?.to_stage_name}</h4>
          <pre>{JSON.stringify(toContent, null, 2)}</pre>
        </div>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="stage-comparison loading">
        <div className="spinner"></div>
        <p>Loading comparison...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="stage-comparison error">
        <p className="error-message">{error}</p>
        <button className="btn btn-secondary" onClick={loadComparison}>
          🔄 Retry
        </button>
      </div>
    );
  }

  return (
    <div className="stage-comparison">
      {/* Header */}
      <div className="comparison-header">
        <h2>Stage Comparison</h2>
        <button className="btn btn-secondary btn-sm" onClick={onClose}>
          ✕ Close
        </button>
      </div>

      {/* View Mode Toggle */}
      <div className="view-mode-toggle">
        <button
          className={viewMode === 'summary' ? 'active' : ''}
          onClick={() => setViewMode('summary')}
        >
          📊 Summary
        </button>
        <button
          className={viewMode === 'sidebyside' ? 'active' : ''}
          onClick={() => setViewMode('sidebyside')}
        >
          ⚖️ Side by Side
        </button>
        <button
          className={viewMode === 'unified' ? 'active' : ''}
          onClick={() => setViewMode('unified')}
        >
          📋 Unified
        </button>
      </div>

      {/* Content */}
      <div className="comparison-content">
        {viewMode === 'summary' && renderSummary()}
        {viewMode === 'sidebyside' && renderSideBySide()}
        {viewMode === 'unified' && renderUnified()}
      </div>
    </div>
  );
}

export default StageComparison;
