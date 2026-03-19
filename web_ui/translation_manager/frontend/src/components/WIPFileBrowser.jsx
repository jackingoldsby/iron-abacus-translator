import React, { useState, useEffect } from 'react';
import { workflowAPI } from '../api/client';
import { showToast } from './Toast';
import './WIPFileBrowser.css';

/**
 * WIPFileBrowser Component
 *
 * Displays Work-In-Progress (WIP) file content for a specific stage.
 * Features:
 * - JSON content preview with syntax highlighting
 * - Download WIP file
 * - View stage-specific logs
 * - Compare with other stages
 * - Expandable sections for better readability
 *
 * Props:
 * - flowRunId: The workflow run ID
 * - stageNum: Stage number (1-7)
 * - stageName: Stage name for display
 * - onCompare: Callback to trigger stage comparison
 */
function WIPFileBrowser({ flowRunId, stageNum, stageName, onCompare }) {
  const [wipContent, setWipContent] = useState(null);
  const [wipLog, setWipLog] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('preview'); // 'preview', 'raw', 'log'
  const [expandedSections, setExpandedSections] = useState(new Set());

  useEffect(() => {
    if (flowRunId && stageNum) {
      loadWIPContent();
      loadWIPLog();
    }
  }, [flowRunId, stageNum]);

  const loadWIPContent = async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await fetch(
        `http://localhost:8000/api/workflow/wip/stage/${flowRunId}/${stageNum}`
      );

      if (!response.ok) {
        if (response.status === 404) {
          setError('WIP file not yet created for this stage');
          setWipContent(null);
          return;
        }
        throw new Error(`Failed to load WIP: ${response.statusText}`);
      }

      const data = await response.json();
      setWipContent(data);
    } catch (err) {
      console.error('Error loading WIP content:', err);
      setError(err.message);
      setWipContent(null);
    } finally {
      setLoading(false);
    }
  };

  const loadWIPLog = async () => {
    try {
      const response = await fetch(
        `http://localhost:8000/api/workflow/logs/stage/${flowRunId}/${stageNum}`
      );

      if (response.ok) {
        const data = await response.json();
        setWipLog(data);
      } else {
        setWipLog(null);
      }
    } catch (err) {
      console.error('Error loading WIP log:', err);
      setWipLog(null);
    }
  };

  const handleDownload = async () => {
    try {
      const response = await fetch(
        `http://localhost:8000/api/workflow/wip/stage/${flowRunId}/${stageNum}/download`
      );

      if (!response.ok) {
        throw new Error('Download failed');
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `stage_${stageNum}_${stageName}.json`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err) {
      console.error('Error downloading WIP:', err);
      showToast('Failed to download WIP file', 'error');
    }
  };

  const toggleSection = (section) => {
    const newExpanded = new Set(expandedSections);
    if (newExpanded.has(section)) {
      newExpanded.delete(section);
    } else {
      newExpanded.add(section);
    }
    setExpandedSections(newExpanded);
  };

  const renderPreview = (data, path = '') => {
    if (!data) return null;

    if (typeof data === 'string') {
      return (
        <div className="preview-string">
          {data.length > 200 ? `${data.substring(0, 200)}...` : data}
        </div>
      );
    }

    if (typeof data === 'number' || typeof data === 'boolean') {
      return <div className="preview-primitive">{String(data)}</div>;
    }

    if (Array.isArray(data)) {
      return (
        <div className="preview-array">
          <div className="preview-array-header">
            Array ({data.length} items)
          </div>
          {data.slice(0, 5).map((item, index) => (
            <div key={index} className="preview-array-item">
              <span className="preview-index">[{index}]</span>
              {renderPreview(item, `${path}[${index}]`)}
            </div>
          ))}
          {data.length > 5 && (
            <div className="preview-more">... {data.length - 5} more items</div>
          )}
        </div>
      );
    }

    if (typeof data === 'object') {
      const keys = Object.keys(data);
      return (
        <div className="preview-object">
          {keys.slice(0, 10).map((key) => {
            const fullPath = path ? `${path}.${key}` : key;
            const isExpanded = expandedSections.has(fullPath);
            const value = data[key];
            const isComplex = typeof value === 'object' && value !== null;

            return (
              <div key={key} className="preview-object-row">
                <div
                  className="preview-object-key"
                  onClick={() => isComplex && toggleSection(fullPath)}
                  style={{ cursor: isComplex ? 'pointer' : 'default' }}
                >
                  {isComplex && (
                    <span className="expand-icon">{isExpanded ? '▼' : '▶'}</span>
                  )}
                  <strong>{key}:</strong>
                </div>
                {isExpanded ? (
                  <div className="preview-object-value-expanded">
                    {renderPreview(value, fullPath)}
                  </div>
                ) : (
                  <div className="preview-object-value">
                    {isComplex ? (
                      <span className="preview-type">
                        {Array.isArray(value) ? `Array(${value.length})` : 'Object'}
                      </span>
                    ) : (
                      renderPreview(value, fullPath)
                    )}
                  </div>
                )}
              </div>
            );
          })}
          {keys.length > 10 && (
            <div className="preview-more">... {keys.length - 10} more fields</div>
          )}
        </div>
      );
    }

    return <div className="preview-null">null</div>;
  };

  if (loading) {
    return (
      <div className="wip-browser loading">
        <div className="spinner"></div>
        <p>Loading WIP file...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="wip-browser error">
        <p className="error-message">{error}</p>
        <button className="btn btn-secondary" onClick={loadWIPContent}>
          🔄 Retry
        </button>
      </div>
    );
  }

  if (!wipContent) {
    return (
      <div className="wip-browser empty">
        <p>No WIP file available for this stage yet.</p>
      </div>
    );
  }

  return (
    <div className="wip-browser">
      {/* Tabs */}
      <div className="wip-tabs">
        <button
          className={`wip-tab ${activeTab === 'preview' ? 'active' : ''}`}
          onClick={() => setActiveTab('preview')}
        >
          📋 Preview
        </button>
        <button
          className={`wip-tab ${activeTab === 'raw' ? 'active' : ''}`}
          onClick={() => setActiveTab('raw')}
        >
          📄 Raw JSON
        </button>
        {wipLog && (
          <button
            className={`wip-tab ${activeTab === 'log' ? 'active' : ''}`}
            onClick={() => setActiveTab('log')}
          >
            📊 Stage Log
          </button>
        )}
      </div>

      {/* Actions */}
      <div className="wip-actions">
        <button className="btn btn-primary btn-sm" onClick={handleDownload}>
          ⬇️ Download
        </button>
        {stageNum > 1 && (
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => onCompare && onCompare(stageNum - 1, stageNum)}
          >
            🔍 Compare with Stage {stageNum - 1}
          </button>
        )}
      </div>

      {/* Content */}
      <div className="wip-content">
        {activeTab === 'preview' && (
          <div className="wip-preview">
            {renderPreview(wipContent)}
          </div>
        )}

        {activeTab === 'raw' && (
          <div className="wip-raw">
            <pre>{JSON.stringify(wipContent, null, 2)}</pre>
          </div>
        )}

        {activeTab === 'log' && wipLog && (
          <div className="wip-log">
            <pre>{JSON.stringify(wipLog, null, 2)}</pre>
          </div>
        )}
      </div>
    </div>
  );
}

export default WIPFileBrowser;
