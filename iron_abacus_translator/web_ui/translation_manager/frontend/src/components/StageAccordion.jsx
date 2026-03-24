import React, { useState, useEffect, useMemo } from 'react';
import { workflowAPI } from '../api/client';
import WIPFileBrowser from './WIPFileBrowser';
import StageComparison from './StageComparison';
import './StageAccordion.css';

/**
 * StageAccordion Component
 *
 * Displays the 7-stage translation pipeline as an expandable accordion.
 * Each stage can be expanded to show:
 * - Stage details and progress
 * - WIP file preview
 * - Stage-specific logs
 * - Actions (download WIP, view logs, etc.)
 *
 * Props:
 * - flowRunId: The workflow run ID to display stages for
 * - workflowStatus: Real-time workflow status from parent (via SSE)
 * - onStageSelect: Callback when a stage is selected for detailed view
 *
 * Memoized to prevent unnecessary re-renders when props haven't changed
 */
const StageAccordion = React.memo(({ flowRunId, workflowStatus, onStageSelect }) => {
  const [expandedStage, setExpandedStage] = useState(null);
  const [comparisonView, setComparisonView] = useState(null); // { fromStage, toStage }

  // Translation pipeline stages configuration
  const PIPELINE_STAGES = [
    { number: 1, name: 'BODY', icon: '📝', color: '#3498db', description: 'Translate body content with cultural footnotes' },
    { number: 2, name: 'METADATA', icon: '📋', color: '#9b59b6', description: 'Translate title, author, publisher' },
    { number: 3, name: 'TOC', icon: '📑', color: '#e67e22', description: 'Translate table of contents' },
    { number: 4, name: 'HEADINGS', icon: '📌', color: '#16a085', description: 'Translate chapter headings' },
    { number: 5, name: 'SPECIAL', icon: '⭐', color: '#f39c12', description: 'Translate front/back matter' },
    { number: 6, name: 'CLEANUP', icon: '🧹', color: '#e74c3c', description: 'Remove redundant footnotes (AI-powered)' },
    { number: 7, name: 'VALIDATION', icon: '✅', color: '#27ae60', description: 'Validate translation completeness' },
  ];

  const toggleStage = (stageNumber) => {
    setExpandedStage(expandedStage === stageNumber ? null : stageNumber);
    if (onStageSelect) {
      onStageSelect(stageNumber);
    }
  };

  const getStageStatus = (stageNumber) => {
    if (!workflowStatus || !workflowStatus.stages) return null;
    return workflowStatus.stages.find(s => s.stage_number === stageNumber);
  };

  const getStageIcon = (status) => {
    if (!status) return '○';
    switch (status.status) {
      case 'completed': return '✓';
      case 'running': return '⚙️';
      case 'failed': return '✗';
      case 'pending': return '○';
      default: return '○';
    }
  };

  const getStageColor = (status) => {
    if (!status) return '#ccc';
    switch (status.status) {
      case 'completed': return '#27ae60';
      case 'running': return '#3498db';
      case 'failed': return '#e74c3c';
      case 'pending': return '#95a5a6';
      default: return '#95a5a6';
    }
  };

  // Format stage name: "BODY" -> "Body"
  const formatStageName = (name) => {
    return name.charAt(0).toUpperCase() + name.slice(1).toLowerCase();
  };

  // Format stage number with leading zeros: 1 -> "001"
  const formatStageNumber = (num) => {
    return String(num).padStart(3, '0');
  };

  if (!workflowStatus) {
    return (
      <div className="stage-accordion-loading">
        <div className="spinner"></div>
        <p>Loading stages...</p>
      </div>
    );
  }

  return (
    <div className="stage-accordion">
      {PIPELINE_STAGES.map((stageConfig) => {
        const status = getStageStatus(stageConfig.number);
        const isExpanded = expandedStage === stageConfig.number;
        const isCurrent = workflowStatus?.current_stage === stageConfig.name;
        const statusIcon = getStageIcon(status);
        const statusColor = getStageColor(status);

        return (
          <div
            key={stageConfig.number}
            className={`stage-item ${isExpanded ? 'expanded' : ''} ${isCurrent ? 'current' : ''}`}
          >
            {/* Stage Header */}
            <div
              className="stage-header"
              onClick={() => toggleStage(stageConfig.number)}
              style={{
                borderLeft: `4px solid ${statusColor}`,
                background: isCurrent ? '#e8f4f8' : 'white'
              }}
            >
              <div className="stage-header-left">
                <div className="stage-icon" style={{ color: stageConfig.color }}>
                  {stageConfig.icon}
                </div>
                <div className="stage-info">
                  <div className="stage-title">
                    <span className="stage-number">{formatStageNumber(stageConfig.number)} -</span>
                    <span className="stage-name"> {formatStageName(stageConfig.name)}</span>
                  </div>
                  <div className="stage-description">{stageConfig.description}</div>
                </div>
              </div>
              <div className="stage-header-right">
                <div className="stage-status-icon" style={{ color: statusColor }}>
                  {statusIcon}
                </div>
                {status && status.progress_pct > 0 && (
                  <div className="stage-progress-text">
                    {status.progress_pct.toFixed(0)}%
                  </div>
                )}
                <div className="expand-arrow">
                  {isExpanded ? '▼' : '▶'}
                </div>
              </div>
            </div>

            {/* Connector Line */}
            {stageConfig.number < PIPELINE_STAGES.length && (
              <div className="stage-connector" style={{ borderColor: statusColor }}></div>
            )}

            {/* Expanded Content */}
            {isExpanded && (
              <div className="stage-content">
                {status ? (
                  <>
                    {/* Progress Bar */}
                    {status.progress_pct > 0 && (
                      <div className="stage-progress-bar">
                        <div
                          className="stage-progress-fill"
                          style={{
                            width: `${status.progress_pct}%`,
                            background: statusColor
                          }}
                        ></div>
                      </div>
                    )}

                    {/* Stage Details */}
                    <div className="stage-details">
                      <div className="detail-row">
                        <span className="detail-label">Status:</span>
                        <span className="detail-value">{status.status}</span>
                      </div>
                      {status.start_time && (
                        <div className="detail-row">
                          <span className="detail-label">Started:</span>
                          <span className="detail-value">
                            {new Date(status.start_time).toLocaleString()}
                          </span>
                        </div>
                      )}
                      {status.end_time && (
                        <div className="detail-row">
                          <span className="detail-label">Ended:</span>
                          <span className="detail-value">
                            {new Date(status.end_time).toLocaleString()}
                          </span>
                        </div>
                      )}
                      {status.duration_seconds && (
                        <div className="detail-row">
                          <span className="detail-label">Duration:</span>
                          <span className="detail-value">
                            {formatDuration(status.duration_seconds)}
                          </span>
                        </div>
                      )}
                      {status.items_processed > 0 && (
                        <div className="detail-row">
                          <span className="detail-label">Items:</span>
                          <span className="detail-value">
                            {status.success_count}/{status.items_processed}
                            {status.error_count > 0 && (
                              <span className="error-count"> ({status.error_count} errors)</span>
                            )}
                          </span>
                        </div>
                      )}
                    </div>

                    {/* WIP File Browser */}
                    <WIPFileBrowser
                      flowRunId={flowRunId}
                      stageNum={stageConfig.number}
                      stageName={stageConfig.name}
                      onCompare={(fromStage, toStage) => setComparisonView({ fromStage, toStage })}
                    />
                  </>
                ) : (
                  <div className="stage-content-empty">
                    <p className="text-muted">Stage not yet started</p>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}

      {/* Stage Comparison Modal */}
      {comparisonView && (
        <div className="comparison-modal-overlay" onClick={() => setComparisonView(null)}>
          <div className="comparison-modal" onClick={(e) => e.stopPropagation()}>
            <StageComparison
              flowRunId={flowRunId}
              fromStage={comparisonView.fromStage}
              toStage={comparisonView.toStage}
              onClose={() => setComparisonView(null)}
            />
          </div>
        </div>
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

function formatDuration(seconds) {
  if (!seconds) return '-';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  } else if (minutes > 0) {
    return `${minutes}m ${secs}s`;
  } else {
    return `${secs}s`;
  }
}

export default StageAccordion;
