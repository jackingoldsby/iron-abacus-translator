import React from 'react';
import './StageProgressBar.css';

/**
 * StageProgressBar Component
 *
 * Compact horizontal stage progress indicators with icons
 * Dynamically renders stages based on workflow data
 */
function StageProgressBar({ stages, currentStage }) {
  // Default icon mapping by common stage names
  const getStageIcon = (stageName) => {
    const name = stageName?.toLowerCase() || '';
    if (name.includes('metadata')) return '📋';
    if (name.includes('toc') || name.includes('table of contents')) return '📑';
    if (name.includes('heading')) return '📝';
    if (name.includes('body') || name.includes('content')) return '📄';
    if (name.includes('special')) return '✨';
    if (name.includes('cleanup') || name.includes('clean')) return '🧹';
    if (name.includes('validation') || name.includes('validate')) return '✅';
    if (name.includes('footnote')) return '📌';
    if (name.includes('translate') || name.includes('translation')) return '🌐';
    return '⚙️'; // Default icon
  };

  const getStatusClass = (status) => {
    switch (status) {
      case 'completed': return 'stage-completed';
      case 'running': return 'stage-running';
      case 'failed': return 'stage-failed';
      case 'pending': return 'stage-pending';
      default: return 'stage-pending';
    }
  };

  // If no stages provided, show empty state
  if (!stages || stages.length === 0) {
    return (
      <div className="stage-progress-bar">
        <div className="card empty-state" style={{ padding: '16px' }}>
          <p>No stage information available</p>
        </div>
      </div>
    );
  }

  return (
    <div className="stage-progress-bar">
      {stages.map((stage) => {
        const status = stage.status || 'pending';
        const progress = stage.progress_pct || 0;
        const isCurrent = currentStage === stage.stage_number;
        const stageName = stage.stage_name || `Stage ${stage.stage_number}`;
        const icon = getStageIcon(stageName);

        return (
          <div
            key={stage.stage_number}
            className={`stage-item ${getStatusClass(status)} ${isCurrent ? 'stage-current' : ''}`}
            title={`${stageName}: ${status} (${progress}%)`}
          >
            <div className="stage-icon">{icon}</div>
            <div className="stage-label">{stageName}</div>
            <div className="stage-progress">
              <div
                className="stage-progress-fill"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default StageProgressBar;
