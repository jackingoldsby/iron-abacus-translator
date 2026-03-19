import React, { useState, useMemo } from 'react';
import './MultiVolumeProgress.css';

/**
 * MultiVolumeProgress Component
 *
 * Shows progress for multi-volume works with:
 * - Volume tabs showing per-volume status
 * - Per-volume progress bar
 * - Overall work progress (weighted average)
 * - Sequential execution indicator
 * - Shared accumulator stats (unique terms across volumes)
 *
 * Props:
 * - volumes: Array of { volume, run_id, status, progress_pct }
 * - activeVolume: Currently selected volume ID
 * - onVolumeSelect: Callback when a volume tab is clicked
 * - accumulatorStats: Optional shared stats across volumes
 */
export default function MultiVolumeProgress({
  volumes = [],
  activeVolume,
  onVolumeSelect,
  accumulatorStats,
}) {
  const [selectedVolume, setSelectedVolume] = useState(activeVolume || volumes[0]?.volume);

  const handleTabClick = (vol) => {
    setSelectedVolume(vol);
    if (onVolumeSelect) onVolumeSelect(vol);
  };

  const overallProgress = useMemo(() => {
    if (!volumes.length) return 0;
    const total = volumes.reduce((sum, v) => sum + (v.progress_pct || 0), 0);
    return total / volumes.length;
  }, [volumes]);

  const currentVolumeIdx = useMemo(() => {
    const idx = volumes.findIndex((v) => v.status === 'running');
    return idx >= 0 ? idx : volumes.findIndex((v) => v.status === 'pending');
  }, [volumes]);

  if (!volumes.length) return null;

  return (
    <div className="multi-volume-progress">
      <h3>Volume Progress</h3>

      {/* Volume Tabs */}
      <div className="volume-tabs">
        {volumes.map((vol) => (
          <button
            key={vol.volume}
            className={`volume-tab ${selectedVolume === vol.volume ? 'active' : ''}`}
            onClick={() => handleTabClick(vol.volume)}
          >
            <span className={`volume-status-dot ${vol.status || 'pending'}`} />
            Vol {vol.volume.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Per-Volume Progress */}
      <div className="volume-details">
        {volumes.map((vol) => (
          <div key={vol.volume} className="volume-progress-row">
            <span className="volume-progress-label">
              Vol {vol.volume.toUpperCase()}
            </span>
            <div className="volume-progress-bar">
              <div
                className="volume-progress-fill"
                style={{
                  width: `${vol.progress_pct || 0}%`,
                  background: getVolumeColor(vol.status),
                }}
              />
            </div>
            <span className="volume-progress-pct">
              {(vol.progress_pct || 0).toFixed(0)}%
            </span>
          </div>
        ))}
      </div>

      {/* Overall Progress */}
      <div className="volume-overall">
        <div className="volume-overall-label">
          Overall Work Progress
        </div>
        <div className="volume-overall-bar">
          <div
            className="volume-overall-fill"
            style={{ width: `${overallProgress}%` }}
          />
        </div>
      </div>

      {/* Sequential notice */}
      <div className="volume-sequential-notice">
        Volumes processed sequentially (accumulator state persists between volumes)
      </div>

      {/* Accumulator Stats */}
      {accumulatorStats && (
        <div className="volume-accumulator">
          <div className="volume-accumulator-title">Shared Accumulator</div>
          <div className="volume-accumulator-stats">
            {accumulatorStats.unique_terms != null && (
              <span className="volume-accumulator-stat">
                Unique terms: <strong>{accumulatorStats.unique_terms}</strong>
              </span>
            )}
            {accumulatorStats.total_footnotes != null && (
              <span className="volume-accumulator-stat">
                Total footnotes: <strong>{accumulatorStats.total_footnotes}</strong>
              </span>
            )}
            {accumulatorStats.removed_duplicates != null && (
              <span className="volume-accumulator-stat">
                Deduped: <strong>{accumulatorStats.removed_duplicates}</strong>
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function getVolumeColor(status) {
  switch (status) {
    case 'completed': return '#4caf50';
    case 'running': return '#2196f3';
    case 'failed': return '#f44336';
    default: return '#bdbdbd';
  }
}
