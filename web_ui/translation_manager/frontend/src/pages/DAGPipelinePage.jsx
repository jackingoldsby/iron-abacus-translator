import React, { useState, useEffect, useCallback, useRef } from 'react';
import DAGVisualization from '../components/DAGVisualization';
import MultiVolumeProgress from '../components/MultiVolumeProgress';
import { worksAPI, dagAPI, authorsAPI, volumesAPI } from '../api/client';
import { showToast } from '../components/Toast';
import './DAGPipelinePage.css';

/**
 * DAGPipelinePage
 *
 * Unified page combining:
 * - Left: Work selector with author/status filtering and volume checkboxes
 * - Center: ReactFlow DAG visualization with live node updates
 * - Right: Slide-in detail panel for selected node
 * - Bottom: Overall progress bar with controls
 */
export default function DAGPipelinePage() {
  // --- Work Selector State ---
  const [works, setWorks] = useState([]);
  const [authors, setAuthors] = useState([]);
  const [search, setSearch] = useState('');
  const [authorFilter, setAuthorFilter] = useState('');
  const [multiVolumeOnly, setMultiVolumeOnly] = useState(false);
  const [selectedWork, setSelectedWork] = useState(null);
  const [workVolumes, setWorkVolumes] = useState(null);
  const [selectedVolumes, setSelectedVolumes] = useState([]);
  const [loadingWorks, setLoadingWorks] = useState(false);

  // --- DAG State ---
  const [dagData, setDagData] = useState(null);
  const [activeRun, setActiveRun] = useState(null);
  const [nodeStatuses, setNodeStatuses] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const sseRef = useRef(null);

  // --- Multi-volume State ---
  const [batchRuns, setBatchRuns] = useState(null);
  const [activeVolumeRunId, setActiveVolumeRunId] = useState(null);

  // ==========================================================================
  // LOAD WORKS & AUTHORS
  // ==========================================================================

  useEffect(() => {
    loadAuthors();
    loadPipelineDefinition();
  }, []);

  useEffect(() => {
    loadWorks();
  }, [search, authorFilter, multiVolumeOnly]);

  const loadAuthors = async () => {
    try {
      const data = await authorsAPI.list();
      setAuthors(data);
    } catch (err) {
      console.error('Failed to load authors:', err);
    }
  };

  const loadWorks = async () => {
    setLoadingWorks(true);
    try {
      const params = {};
      if (search) params.search = search;
      if (authorFilter) params.author = authorFilter;
      if (multiVolumeOnly) params.min_volumes = 2;

      // Build query string manually since worksAPI.list only takes search
      const queryParts = [];
      if (search) queryParts.push(`search=${encodeURIComponent(search)}`);
      if (authorFilter) queryParts.push(`author=${encodeURIComponent(authorFilter)}`);
      if (multiVolumeOnly) queryParts.push('min_volumes=2');

      // Use the enhanced works API with filters
      const response = await fetch(
        `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/api/works?${queryParts.join('&')}`
      );
      const data = await response.json();
      setWorks(data);
    } catch (err) {
      console.error('Failed to load works:', err);
      // Fallback to basic search
      try {
        const data = await worksAPI.list(search);
        setWorks(data);
      } catch (e) {
        console.error('Fallback also failed:', e);
      }
    }
    setLoadingWorks(false);
  };

  const loadPipelineDefinition = async () => {
    try {
      const data = await dagAPI.getPipeline('v2');
      setDagData(data);
    } catch (err) {
      console.error('Failed to load pipeline definition:', err);
    }
  };

  // ==========================================================================
  // WORK SELECTION
  // ==========================================================================

  const handleWorkSelect = async (work) => {
    if (selectedWork?.work_number === work.work_number) {
      setSelectedWork(null);
      setWorkVolumes(null);
      setSelectedVolumes([]);
      return;
    }

    setSelectedWork(work);
    setSelectedVolumes([]);

    if (work.total_volumes > 1) {
      try {
        const volData = await volumesAPI.get(work.work_number);
        setWorkVolumes(volData);
        // Pre-select all available volumes
        const available = volData.volumes
          .filter((v) => v.status !== 'missing')
          .map((v) => v.volume);
        setSelectedVolumes(available);
      } catch (err) {
        console.error('Failed to load volumes:', err);
        setWorkVolumes(null);
      }
    } else {
      setWorkVolumes(null);
      setSelectedVolumes(['single']);
    }
  };

  const toggleVolume = (vol) => {
    setSelectedVolumes((prev) =>
      prev.includes(vol) ? prev.filter((v) => v !== vol) : [...prev, vol]
    );
  };

  // ==========================================================================
  // DAG RUN
  // ==========================================================================

  const startPipeline = async () => {
    if (!selectedWork || selectedVolumes.length === 0) return;

    try {
      const result = await dagAPI.startRun(
        selectedWork.work_number,
        selectedVolumes,
        'v2'
      );

      if (result.batch_id) {
        // Multi-volume: track all runs
        setBatchRuns(result.runs);
        const firstRun = result.runs[0];
        setActiveRun(firstRun.run_id);
        setActiveVolumeRunId(firstRun.run_id);
        connectSSE(firstRun.run_id);
      } else {
        // Single volume
        setActiveRun(result.run_id);
        setBatchRuns(null);
        connectSSE(result.run_id);
      }

      showToast(`Pipeline started for ${selectedWork.work_number}`, 'success');
    } catch (err) {
      console.error('Failed to start pipeline:', err);
      showToast(`Failed to start pipeline: ${err.message}`, 'error');
    }
  };

  const connectSSE = useCallback((runId) => {
    // Close existing SSE
    if (sseRef.current) {
      sseRef.current.close();
    }

    const eventSource = dagAPI.streamRun(
      runId,
      (data) => {
        if (data.type === 'initial') {
          setNodeStatuses(data.run?.node_statuses || {});
        } else if (data.type === 'node_update') {
          setNodeStatuses((prev) => ({
            ...prev,
            [data.node_id]: {
              status: data.status,
              progress_pct: data.progress_pct || 0,
              duration_seconds: data.duration_seconds,
            },
          }));
        }
      },
      (error) => {
        console.error('SSE disconnected:', error);
      }
    );

    sseRef.current = eventSource;
  }, []);

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => {
      if (sseRef.current) sseRef.current.close();
    };
  }, []);

  // ==========================================================================
  // NODE ACTIONS
  // ==========================================================================

  const handleNodeClick = (nodeId, nodeData) => {
    setSelectedNode({ id: nodeId, ...nodeData });
    setDetailOpen(true);
  };

  const handleNodeAction = async (action, nodeId) => {
    if (!activeRun) return;

    try {
      switch (action) {
        case 'retry':
          await dagAPI.retryNode(activeRun, nodeId);
          showToast(`Retrying node: ${nodeId}`, 'info');
          break;
        case 'skip':
          await dagAPI.skipNode(activeRun, nodeId);
          showToast(`Skipped node: ${nodeId}`, 'info');
          break;
        case 'validate':
          await dagAPI.validateNode(activeRun, nodeId);
          showToast(`Validated node: ${nodeId}`, 'success');
          break;
        case 'view_logs':
          setSelectedNode((prev) => (prev?.id === nodeId ? prev : { id: nodeId }));
          setDetailOpen(true);
          break;
      }
    } catch (err) {
      showToast(`Action failed: ${err.message}`, 'error');
    }
  };

  // ==========================================================================
  // COMPUTED VALUES
  // ==========================================================================

  const overallProgress = nodeStatuses
    ? (() => {
        const entries = Object.values(nodeStatuses);
        if (!entries.length) return 0;
        const done = entries.filter(
          (s) => s.status === 'completed' || s.status === 'skipped'
        ).length;
        return Math.round((done / entries.length) * 100);
      })()
    : 0;

  const runningNodeCount = nodeStatuses
    ? Object.values(nodeStatuses).filter((s) => s.status === 'running').length
    : 0;

  const failedNodeCount = nodeStatuses
    ? Object.values(nodeStatuses).filter((s) => s.status === 'failed').length
    : 0;

  // ==========================================================================
  // RENDER
  // ==========================================================================

  return (
    <div className="dag-pipeline-page">
      {/* ---- LEFT PANEL: Work Selector ---- */}
      <div className="dag-work-selector">
        <div className="dag-work-selector-header">
          <h3>Select Work</h3>
          <input
            className="dag-search-bar"
            type="text"
            placeholder="Search title, author, or work number..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="dag-filters">
            <select
              className="dag-filter-select"
              value={authorFilter}
              onChange={(e) => setAuthorFilter(e.target.value)}
            >
              <option value="">All Authors</option>
              {authors.map((a) => (
                <option key={a.author_chinese} value={a.author_chinese}>
                  {a.author_chinese}
                  {a.author_english ? ` (${a.author_english})` : ''}
                  {` [${a.work_count}]`}
                </option>
              ))}
            </select>
            <button
              className={`dag-filter-toggle ${multiVolumeOnly ? 'active' : ''}`}
              onClick={() => setMultiVolumeOnly(!multiVolumeOnly)}
            >
              Multi-vol
            </button>
          </div>
        </div>

        <div className="dag-work-list">
          {loadingWorks && <div style={{ padding: 12, color: '#999' }}>Loading...</div>}
          {works.map((work) => (
            <div
              key={work.work_number}
              className={`dag-work-item ${
                selectedWork?.work_number === work.work_number ? 'selected' : ''
              }`}
              onClick={() => handleWorkSelect(work)}
            >
              <div className="dag-work-title">
                {work.title_chinese}
                {work.title_english && (
                  <span style={{ fontWeight: 400, color: '#888', marginLeft: 6 }}>
                    {work.title_english}
                  </span>
                )}
              </div>
              <div className="dag-work-subtitle">
                <span>{work.author_chinese}</span>
                <span>{work.work_number}</span>
                {work.total_volumes > 1 && (
                  <span className="dag-work-badge volumes">
                    {work.total_volumes} vols
                  </span>
                )}
              </div>

              {/* Volume selector (expanded) */}
              {selectedWork?.work_number === work.work_number && workVolumes && (
                <div className="dag-volume-selector">
                  {workVolumes.volumes.map((vol) => (
                    <label key={vol.volume} className="dag-volume-checkbox">
                      <input
                        type="checkbox"
                        checked={selectedVolumes.includes(vol.volume)}
                        onChange={() => toggleVolume(vol.volume)}
                        disabled={vol.status === 'missing'}
                      />
                      Vol {vol.volume.toUpperCase()}
                      <span
                        className="dag-volume-status"
                        style={{
                          background:
                            vol.status === 'completed'
                              ? '#e8f5e9'
                              : vol.status === 'missing'
                              ? '#ffebee'
                              : '#f5f5f5',
                          color:
                            vol.status === 'completed'
                              ? '#2e7d32'
                              : vol.status === 'missing'
                              ? '#c62828'
                              : '#666',
                        }}
                      >
                        {vol.status}
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>

        <button
          className="dag-start-button"
          disabled={!selectedWork || selectedVolumes.length === 0}
          onClick={startPipeline}
        >
          Start Pipeline
          {selectedWork && ` (${selectedWork.work_number})`}
        </button>
      </div>

      {/* ---- CENTER PANEL: DAG + Multi-Volume ---- */}
      <div className="dag-center-panel">
        <div className="dag-graph-container">
          {activeRun ? (
            <DAGVisualization
              dagData={dagData}
              nodeStatuses={nodeStatuses}
              onNodeClick={handleNodeClick}
              onNodeAction={handleNodeAction}
            />
          ) : (
            <div className="dag-empty-state">
              {dagData ? (
                <DAGVisualization dagData={dagData} nodeStatuses={null} />
              ) : (
                <div>
                  Select a work and start the pipeline
                  <br />
                  to see the DAG visualization
                </div>
              )}
            </div>
          )}
        </div>

        {/* Multi-volume progress (when applicable) */}
        {batchRuns && batchRuns.length > 1 && (
          <MultiVolumeProgress
            volumes={batchRuns.map((r) => ({
              volume: r.volume,
              run_id: r.run_id,
              status: nodeStatuses ? 'running' : 'pending',
              progress_pct: r.run_id === activeVolumeRunId ? overallProgress : 0,
            }))}
            activeVolume={
              batchRuns.find((r) => r.run_id === activeVolumeRunId)?.volume
            }
            onVolumeSelect={(vol) => {
              const run = batchRuns.find((r) => r.volume === vol);
              if (run) {
                setActiveVolumeRunId(run.run_id);
                setActiveRun(run.run_id);
                connectSSE(run.run_id);
              }
            }}
          />
        )}
      </div>

      {/* ---- BOTTOM BAR ---- */}
      {activeRun && (
        <div className="dag-bottom-bar">
          <div className="dag-bottom-progress">
            <div className="dag-bottom-progress-bar">
              <div
                className="dag-bottom-progress-fill"
                style={{
                  width: `${overallProgress}%`,
                  background:
                    failedNodeCount > 0
                      ? '#e53935'
                      : overallProgress >= 100
                      ? '#4caf50'
                      : '#2196f3',
                }}
              />
            </div>
          </div>
          <div className="dag-bottom-stats">
            <span className="dag-bottom-stat">
              Progress: <strong>{overallProgress}%</strong>
            </span>
            {runningNodeCount > 0 && (
              <span className="dag-bottom-stat">
                Running: <strong>{runningNodeCount}</strong>
              </span>
            )}
            {failedNodeCount > 0 && (
              <span className="dag-bottom-stat" style={{ color: '#e53935' }}>
                Failed: <strong>{failedNodeCount}</strong>
              </span>
            )}
          </div>
          <div className="dag-bottom-controls">
            <button onClick={() => connectSSE(activeRun)}>Refresh</button>
            <button
              className="cancel"
              onClick={() => {
                if (sseRef.current) sseRef.current.close();
                setActiveRun(null);
                setNodeStatuses(null);
                setBatchRuns(null);
              }}
            >
              Stop
            </button>
          </div>
        </div>
      )}

      {/* ---- DETAIL PANEL (slide-in) ---- */}
      <div className={`dag-detail-panel ${detailOpen ? 'open' : ''}`}>
        <div className="dag-detail-header">
          <h3>{selectedNode?.display_name || 'Node Details'}</h3>
          <button className="dag-detail-close" onClick={() => setDetailOpen(false)}>
            ×
          </button>
        </div>

        {selectedNode && (
          <>
            <div className="dag-detail-section">
              <h4>Info</h4>
              <div className="dag-detail-info">
                <span className="dag-detail-label">ID</span>
                <span className="dag-detail-value">{selectedNode.id}</span>
                <span className="dag-detail-label">Type</span>
                <span className="dag-detail-value">{selectedNode.node_type}</span>
                <span className="dag-detail-label">Status</span>
                <span className="dag-detail-value">
                  {nodeStatuses?.[selectedNode.id]?.status || selectedNode.status || 'pending'}
                </span>
                {selectedNode.metadata?.description && (
                  <>
                    <span className="dag-detail-label">Description</span>
                    <span className="dag-detail-value">
                      {selectedNode.metadata.description}
                    </span>
                  </>
                )}
              </div>
            </div>

            <div className="dag-detail-section">
              <h4>Dependencies</h4>
              {selectedNode.dependencies?.length > 0 ? (
                <ul style={{ margin: 0, paddingLeft: 20, fontSize: 13 }}>
                  {selectedNode.dependencies.map((dep) => (
                    <li key={dep}>{dep}</li>
                  ))}
                </ul>
              ) : (
                <span style={{ fontSize: 13, color: '#999' }}>None (root node)</span>
              )}
            </div>

            {activeRun && (
              <div className="dag-detail-actions">
                <button
                  className="primary"
                  onClick={() => handleNodeAction('retry', selectedNode.id)}
                >
                  Retry
                </button>
                <button onClick={() => handleNodeAction('skip', selectedNode.id)}>
                  Skip
                </button>
                {selectedNode.node_type === 'quality_gate' && (
                  <button
                    className="primary"
                    onClick={() => handleNodeAction('validate', selectedNode.id)}
                  >
                    Force Pass
                  </button>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
