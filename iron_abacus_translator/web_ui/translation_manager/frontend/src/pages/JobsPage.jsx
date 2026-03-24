import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { jobsAPI, JobWebSocket, workflowAPI, worksAPI } from '../api/client';
import { MultiLevelProgress, ProgressBadge } from '../components/ProgressBar';
import StageProgressBar from '../components/StageProgressBar';
import PrefectVisualization from '../components/PrefectVisualization';
import WorkflowControls from '../components/WorkflowControls';
import WorkflowTerminal from '../components/WorkflowTerminal';
import StartWorkflowModal from '../components/StartWorkflowModal';
import Tooltip from '../components/Tooltip';
import { showToast } from '../components/Toast';
import {
  formatRelativeTime,
  formatFullTimestamp,
  formatDuration,
  calculateETA,
  getETAColorClass
} from '../utils/timeFormatting';
import './JobsPage.css';

function JobsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [viewMode, setViewMode] = useState('workflow'); // 'workflow' or 'jobs'
  const [workflowView, setWorkflowView] = useState('custom'); // 'custom' or 'prefect'
  const [workflows, setWorkflows] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedJob, setSelectedJob] = useState(null);
  const [detailedProgress, setDetailedProgress] = useState(null);
  const [activeWorkflow, setActiveWorkflow] = useState(null); // { flowRunId, workId, volume }
  const [workflowStatus, setWorkflowStatus] = useState(null); // Real-time workflow status from SSE
  const [selectedWorkFilter, setSelectedWorkFilter] = useState('all'); // Work filter: 'all' or specific work_id
  const [showStartModal, setShowStartModal] = useState(false); // Start Workflow modal
  const [workMetadata, setWorkMetadata] = useState({}); // Cache for work title/author
  const wsRef = useRef(null);
  const progressPollRef = useRef(null);
  const eventSourceRef = useRef(null); // Single SSE connection for workflow updates

  useEffect(() => {
    loadWorkflows();
    loadJobs();

    // Handle URL parameters
    const workflowId = searchParams.get('workflow_id');
    const jobId = searchParams.get('job_id');

    if (workflowId) {
      setViewMode('workflow');
      loadAndSelectWorkflow(workflowId);
    } else if (jobId) {
      setViewMode('jobs');
      loadAndSelectJob(jobId);
    }

    // Setup WebSocket connection
    wsRef.current = new JobWebSocket(handleWebSocketMessage);
    wsRef.current.connect();

    return () => {
      if (wsRef.current) {
        wsRef.current.disconnect();
      }
      if (progressPollRef.current) {
        clearInterval(progressPollRef.current);
      }
    };
  }, []);

  // Load detailed progress when a job is selected (no polling - workflow view uses SSE)
  useEffect(() => {
    if (selectedJob && selectedJob.current_work) {
      // Initial load only - no polling
      loadDetailedProgress(selectedJob.job_id);
    } else {
      setDetailedProgress(null);
    }
  }, [selectedJob?.job_id]);

  // Single SSE connection for real-time workflow updates
  useEffect(() => {
    // Close any existing connection
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    if (!activeWorkflow?.flowRunId) {
      setWorkflowStatus(null);
      return;
    }

    // Create new SSE connection for active workflow
    eventSourceRef.current = workflowAPI.streamProgress(
      activeWorkflow.flowRunId,
      (data) => {
        // Update workflow status from stream
        setWorkflowStatus(data);
      },
      (error) => {
        console.error('Workflow SSE error:', error);
      }
    );

    // Cleanup on unmount or workflow change
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, [activeWorkflow?.flowRunId]);

  const loadJobs = async () => {
    try {
      setLoading(true);
      const data = await jobsAPI.list();
      setJobs(data);
    } catch (error) {
      console.error('Failed to load jobs:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadWorkflows = async () => {
    try {
      const data = await workflowAPI.list(100);
      setWorkflows(data);

      // Fetch work metadata for all unique work IDs
      await loadWorkMetadata(data);
    } catch (error) {
      console.error('Failed to load workflows:', error);
      setWorkflows([]);
    }
  };

  // Load work metadata (title/author) for all workflows
  const loadWorkMetadata = async (workflowData) => {
    const workIds = new Set();

    // Collect unique work IDs from workflows
    workflowData?.forEach(wf => {
      if (wf.work_id) workIds.add(wf.work_id);
    });

    // Fetch metadata for each work
    const metadataPromises = Array.from(workIds).map(async workId => {
      try {
        const data = await worksAPI.get(workId);
        return [workId, data];
      } catch (error) {
        console.warn(`Failed to load metadata for ${workId}:`, error);
        return [workId, null];
      }
    });

    const metadataResults = await Promise.all(metadataPromises);
    const metadataMap = Object.fromEntries(metadataResults);
    setWorkMetadata(metadataMap);
  };

  const loadAndSelectWorkflow = async (flowRunId) => {
    try {
      const status = await workflowAPI.getStatus(flowRunId);
      setActiveWorkflow({
        flowRunId: status.flow_run_id,
        workId: status.work_id,
        volume: status.volume
      });
    } catch (error) {
      console.error('Failed to load workflow:', error);
      showToast('Failed to load workflow - it may have been deleted', 'error');
    }
  };

  const loadAndSelectJob = async (jobId) => {
    try {
      const job = await jobsAPI.get(jobId);
      setSelectedJob(job);
    } catch (error) {
      console.error('Failed to load job:', error);
      showToast('Failed to load job - it may have been deleted', 'error');
    }
  };

  const loadDetailedProgress = async (jobId) => {
    try {
      const progress = await jobsAPI.getDetailedProgress(jobId);
      setDetailedProgress(progress);
    } catch (error) {
      // Not all jobs will have detailed progress (e.g., queued jobs)
      console.debug('No detailed progress available:', error);
      setDetailedProgress(null);
    }
  };

  const handleWebSocketMessage = (message) => {
    console.log('WebSocket message:', message);

    // Update jobs list based on message type
    if (message.type === 'job_update' || message.type === 'job_progress' || message.type === 'job_complete') {
      setJobs(prevJobs => {
        return prevJobs.map(job => {
          if (job.job_id === message.job_id) {
            return {
              ...job,
              ...message,
            };
          }
          return job;
        });
      });

      // Update selected job if it's the one being updated
      if (selectedJob && selectedJob.job_id === message.job_id) {
        setSelectedJob(prev => ({ ...prev, ...message }));
      }

      // Update detailed progress if included
      if (message.detailed_progress) {
        setDetailedProgress(message.detailed_progress);
      }
    }

    // Handle real-time progress updates
    if (message.type === 'progress_update' && selectedJob && selectedJob.job_id === message.job_id) {
      if (message.detailed_progress) {
        setDetailedProgress(message.detailed_progress);
      }
    }

    // Handle work completion
    if (message.type === 'work_complete' && selectedJob && selectedJob.job_id === message.job_id) {
      if (message.detailed_progress) {
        setDetailedProgress(message.detailed_progress);
      }
    }
  };

  const cancelJob = async (jobId) => {
    if (!confirm('Are you sure you want to cancel this job?')) {
      return;
    }

    try {
      await jobsAPI.cancel(jobId);
      showToast('Job cancellation requested', 'success');
      loadJobs();
    } catch (error) {
      console.error('Failed to cancel job:', error);
      showToast('Failed to cancel job', 'error');
    }
  };

  const refreshJobs = () => {
    loadJobs();
    loadWorkflows();
  };

  const startWorkflow = async (workflowId, workId, volume = null) => {
    try {
      const workflow = await workflowAPI.start(workflowId, workId, volume, {}, false);

      setActiveWorkflow({
        flowRunId: workflow.flow_run_id,
        workflowId: workflow.workflow_id,
        workflowName: workflow.workflow_name,
        workId: workId,
        volume: volume
      });
      setViewMode('workflow');

      // Refresh workflow list
      loadWorkflows();

      showToast(`Workflow started successfully! Flow Run ID: ${workflow.flow_run_id}`, 'success', 6000);
    } catch (error) {
      console.error('Error starting workflow:', error);
      showToast(`Failed to start workflow: ${error.message}`, 'error');
    }
  };

  const handleStartWorkflowSubmit = ({ workflowId, workflowName, workId, volume }) => {
    startWorkflow(workflowId, workId, volume);
    showToast('success', `Starting ${workflowName} for ${workId}${volume ? ` (Vol ${volume})` : ''}...`);
  };

  const selectWorkflow = (workflow) => {
    setActiveWorkflow({
      flowRunId: workflow.flow_run_id,
      workId: workflow.work_id,
      volume: workflow.volume
    });
  };

  const handleWorkflowComplete = (status) => {
    console.log('Workflow completed:', status);
    const toastType = status.status === 'completed' ? 'success' : 'warning';
    showToast(`Workflow ${status.status}`, toastType, 6000);

    // Refresh jobs list
    loadJobs();

    // Optionally close workflow view
    // setShowWorkflowView(false);
  };

  // Extract unique work IDs from workflows and jobs for filter dropdown
  const uniqueWorkIds = useMemo(() => {
    const ids = new Set();

    // Add work IDs from workflows (single work_id per workflow)
    workflows.forEach(wf => {
      if (wf.work_id) ids.add(wf.work_id);
    });

    // Add work IDs from legacy jobs (can have multiple work_numbers per job)
    jobs.forEach(job => {
      if (job.work_numbers && Array.isArray(job.work_numbers)) {
        job.work_numbers.forEach(workId => ids.add(workId));
      }
    });

    // Return sorted list with 'all' at the beginning
    return ['all', ...Array.from(ids).sort()];
  }, [workflows, jobs]);

  // Filter workflows based on selected work
  const filteredWorkflows = useMemo(() => {
    if (selectedWorkFilter === 'all') return workflows;
    return workflows.filter(wf => wf.work_id === selectedWorkFilter);
  }, [workflows, selectedWorkFilter]);

  // Filter jobs based on selected work (batch jobs appear if ANY work_number matches)
  const filteredJobs = useMemo(() => {
    if (selectedWorkFilter === 'all') return jobs;
    return jobs.filter(job =>
      job.work_numbers && job.work_numbers.includes(selectedWorkFilter)
    );
  }, [jobs, selectedWorkFilter]);

  // Get count for each work ID (for dropdown display)
  const workCounts = useMemo(() => {
    const counts = {};
    uniqueWorkIds.forEach(workId => {
      if (workId === 'all') {
        counts[workId] = workflows.length + jobs.length;
      } else {
        const workflowCount = workflows.filter(wf => wf.work_id === workId).length;
        const jobCount = jobs.filter(job => job.work_numbers?.includes(workId)).length;
        counts[workId] = workflowCount + jobCount;
      }
    });
    return counts;
  }, [uniqueWorkIds, workflows, jobs]);

  if (loading) {
    return (
      <div className="empty-state">
        <div className="spinner"></div>
        <p>Loading translation jobs...</p>
      </div>
    );
  }

  return (
    <div>
      {/* Start Workflow Modal */}
      <StartWorkflowModal
        isOpen={showStartModal}
        onClose={() => setShowStartModal(false)}
        onSubmit={handleStartWorkflowSubmit}
      />

      {/* Header - Two Row Layout */}
      <div className="jobs-header">
        {/* Row 1: Title + Action Buttons */}
        <div className="jobs-header-title">
          <h2>Translation Management</h2>
          <div className="jobs-actions-group">
            <button
              className="btn btn-secondary"
              onClick={() => navigate('/jobs/all')}
              title="Back to All Jobs"
            >
              ← Back
            </button>
            {viewMode === 'workflow' && (
              <button
                className="btn btn-success"
                onClick={() => setShowStartModal(true)}
              >
                ⚡ Start Workflow
              </button>
            )}
            <button className="btn btn-primary" onClick={refreshJobs}>
              🔄 Refresh
            </button>
          </div>
        </div>

        {/* Row 2: View Controls + Filters */}
        <div className="jobs-header-controls">
          {/* View Mode Toggle */}
          <div className="view-mode-toggle">
            <button
              className={viewMode === 'workflow' ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm'}
              onClick={() => setViewMode('workflow')}
            >
              ⚡ Workflows
            </button>
            <button
              className={viewMode === 'jobs' ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm'}
              onClick={() => setViewMode('jobs')}
            >
              ⚙️ Legacy Jobs
            </button>
          </div>

          {/* Work Filter Dropdown */}
          <div className="work-filter-container">
            <label htmlFor="work-filter" className="work-filter-label">
              Filter by Work:
            </label>
            <select
              id="work-filter"
              className="form-control work-filter-select"
              value={selectedWorkFilter}
              onChange={(e) => setSelectedWorkFilter(e.target.value)}
            >
              {uniqueWorkIds.map(workId => (
                <option key={workId} value={workId}>
                  {workId === 'all'
                    ? `All Works (${workCounts[workId] || 0})`
                    : `${workId} (${workCounts[workId] || 0})`
                  }
                </option>
              ))}
            </select>
          </div>

          {/* Workflow Visualization Toggle */}
          {viewMode === 'workflow' && activeWorkflow && (
            <div className="workflow-viz-toggle">
              <button
                className={workflowView === 'custom' ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm'}
                onClick={() => setWorkflowView('custom')}
                title="Stage progress view with terminal and controls"
              >
                📊 Stage View
              </button>
              <button
                className={workflowView === 'prefect' ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm'}
                onClick={() => setWorkflowView('prefect')}
                title="Prefect flow visualization"
              >
                🌊 Prefect View
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Workflow View */}
      {viewMode === 'workflow' && (
        filteredWorkflows.length === 0 && !activeWorkflow ? (
          <div className="empty-state">
            <h3>No workflows {selectedWorkFilter !== 'all' ? `for ${selectedWorkFilter}` : ''}</h3>
            <p>Click "Start New Workflow" to begin translating a work with the 7-stage pipeline</p>
          </div>
        ) : (
          <div className="workflow-detail-grid">
            {/* Left: Workflow List */}
            <div className="workflow-list-column">
              <h3 className="column-header">Workflows</h3>

              {/* Workflow Filter Dropdown */}
              <div className="workflow-list-filter">
                <select
                  className="form-control"
                  value={selectedWorkFilter}
                  onChange={(e) => setSelectedWorkFilter(e.target.value)}
                >
                  {uniqueWorkIds.map(workId => (
                    <option key={workId} value={workId}>
                      {workId === 'all'
                        ? `All Works (${workCounts[workId] || 0})`
                        : `${workId} (${workCounts[workId] || 0})`
                      }
                    </option>
                  ))}
                </select>
              </div>

              <div className="workflow-count-badge">
                {filteredWorkflows.length} of {workflows.length}
              </div>

              {filteredWorkflows.map(workflow => {
                const metadata = workMetadata[workflow.work_id];
                const title = metadata?.title_english || metadata?.title_chinese || workflow.work_id;
                const author = metadata?.author_english || metadata?.author_chinese || '';

                // Calculate ETA for running workflows
                const isRunning = workflow.status?.toLowerCase() === 'running';
                const progress = workflow.overall_progress_pct || 0;
                const eta = isRunning && progress > 0
                  ? calculateETA(progress, workflow.duration_seconds, workflow.status)
                  : null;
                const etaColorClass = isRunning && progress > 0
                  ? getETAColorClass(progress, workflow.duration_seconds)
                  : 'eta-unknown';

                // Tooltip content
                const tooltipContent = (
                  <div>
                    <h4>{title}</h4>
                    {author && <p><span className="label">by</span> <span className="value">{author}</span></p>}
                    <hr />
                    <p><span className="label">Work ID:</span> <span className="value"><code>{workflow.work_id}</code></span></p>
                    {workflow.volume && <p><span className="label">Volume:</span> <span className="value">{workflow.volume}</span></p>}
                    {workflow.workflow_name && <p><span className="label">Workflow:</span> <span className="value">{workflow.workflow_name}</span></p>}
                    <hr />
                    <p><span className="label">Started:</span> <span className="value">{formatFullTimestamp(workflow.start_time)}</span></p>
                    <p><span className="label">Elapsed:</span> <span className="value">{formatDuration(workflow.duration_seconds)}</span></p>
                    {eta && <p><span className="label">ETA:</span> <span className="value">{eta}</span></p>}
                    {workflow.current_stage && <p><span className="label">Stage:</span> <span className="value">{workflow.current_stage}</span></p>}
                  </div>
                );

                return (
                  <Tooltip key={workflow.flow_run_id} content={tooltipContent}>
                    <div
                      className={`workflow-card ${activeWorkflow?.flowRunId === workflow.flow_run_id ? 'active' : ''}`}
                      onClick={() => selectWorkflow(workflow)}
                    >
                      <div className="workflow-header">
                        <div className="workflow-title">
                          <div><strong>{workflow.work_id}</strong>{workflow.volume && <span className="text-muted"> (Vol {workflow.volume})</span>}</div>
                          {metadata && (
                            <>
                              <div className="text-sm text-muted" style={{ marginTop: '4px' }}>{title}</div>
                              {author && <div className="text-xs text-muted">by {author}</div>}
                            </>
                          )}
                          {workflow.workflow_name && (
                            <div className="text-xs" style={{ marginTop: '4px', color: '#667eea' }}>
                              ⚡ {workflow.workflow_name}
                            </div>
                          )}
                        </div>
                        <div className="workflow-timestamp text-sm text-muted" title={formatFullTimestamp(workflow.start_time)}>
                          {formatRelativeTime(workflow.start_time)}
                        </div>
                      </div>
                      <div className="workflow-status">
                        <span className={`badge badge-${getWorkflowStatusColor(workflow.status)}`}>
                          {getWorkflowStatusLabel(workflow.status)}
                        </span>
                        {workflow.overall_progress_pct > 0 && (
                          <span className="text-xs text-muted">{workflow.overall_progress_pct.toFixed(0)}%</span>
                        )}
                      </div>
                      <div className="workflow-footer" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '8px' }}>
                        <div className="text-xs text-muted">
                          {formatDuration(workflow.duration_seconds)}
                        </div>
                        {eta && (
                          <div className={`text-xs ${etaColorClass}`} style={{ fontWeight: 600 }}>
                            ETA: {eta}
                          </div>
                        )}
                      </div>
                    </div>
                  </Tooltip>
                );
              })}
            </div>

            {/* Center: Stage View OR Prefect View */}
            <div className="workflow-center-column">
              {activeWorkflow ? (
                workflowView === 'custom' ? (
                  /* Stage Progress View */
                  <>
                    <StageProgressBar
                      stages={workflowStatus?.stages}
                      currentStage={workflowStatus?.current_stage}
                    />

                    <div className="workflow-controls-container">
                      <WorkflowControls
                        flowRunId={activeWorkflow.flowRunId}
                        workflowStatus={workflowStatus}
                        onCancel={() => {
                          loadWorkflows();
                          setActiveWorkflow(null);
                        }}
                      />
                    </div>
                  </>
                ) : (
                  /* Prefect Flow Visualization */
                  <>
                    <PrefectVisualization
                      flowRunId={activeWorkflow.flowRunId}
                      height={600}
                    />

                    <div className="workflow-controls-container">
                      <WorkflowControls
                        flowRunId={activeWorkflow.flowRunId}
                        workflowStatus={workflowStatus}
                        onCancel={() => {
                          loadWorkflows();
                          setActiveWorkflow(null);
                        }}
                      />
                    </div>
                  </>
                )
              ) : (
                <div className="card empty-state">
                  <p>Select a workflow to view progress</p>
                </div>
              )}
            </div>

            {/* Right: Live Log Terminal */}
            <div className="workflow-terminal-column">
              <h3 className="column-header">Live Translation Log</h3>
              {activeWorkflow ? (
                <WorkflowTerminal
                  flowRunId={activeWorkflow.flowRunId}
                  workflowStatus={workflowStatus}
                  maxLines={200}
                  height={600}
                />
              ) : (
                <div className="card empty-state" style={{ height: '600px' }}>
                  <p>Select a workflow to view live logs</p>
                </div>
              )}
            </div>
          </div>
        )
      )}

      {/* Legacy Jobs View */}
      {viewMode === 'jobs' && (
        filteredJobs.length === 0 ? (
          <div className="empty-state">
            <h3>No translation jobs {selectedWorkFilter !== 'all' ? `for ${selectedWorkFilter}` : ''}</h3>
            <p>Go to Works Catalog to create your first translation job</p>
          </div>
        ) : (
          <div className="grid grid-2">
          {/* Jobs List */}
          <div>
            <h3 style={{ fontSize: '16px', marginBottom: '12px' }}>
              Legacy Jobs {selectedWorkFilter !== 'all' && `(${selectedWorkFilter})`}
              <span style={{ marginLeft: '8px', fontSize: '13px', color: '#999' }}>
                {filteredJobs.length} of {jobs.length}
              </span>
            </h3>
            {filteredJobs.map(job => (
              <div
                key={job.job_id}
                className="card mb-2"
                style={{
                  cursor: 'pointer',
                  border: selectedJob?.job_id === job.job_id ? '2px solid #3498db' : 'none'
                }}
                onClick={() => setSelectedJob(job)}
              >

                {/* Progress Bar */}
                {(job.status === 'running' || job.status === 'queued') && (
                  <div className="progress-bar mt-1">
                    <div
                      className="progress-fill"
                      style={{
                        width: `${job.progress || 0}%`,
                        backgroundColor: getProgressColor(job.progress || 0)
                      }}
                    >
                      {job.progress ? `${job.progress.toFixed(0)}%` : 'Queued'}
                    </div>
                  </div>
                )}

                {/* Current Work */}
                {job.current_work && (
                  <div className="text-sm mt-1">
                    Currently: <strong>{job.current_work}</strong>
                  </div>
                )}

                {/* Summary */}
                <div className="flex flex-gap mt-1 text-sm">
                  <span className="badge badge-success">
                    ✓ {job.completed_works?.length || 0}
                  </span>
                  <span className="badge badge-danger">
                    ✗ {job.failed_works?.length || 0}
                  </span>
                </div>

                {/* Actions */}
                {job.status === 'running' && (
                  <div className="mt-1">
                    <button
                      className="btn btn-danger btn-sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        cancelJob(job.job_id);
                      }}
                    >
                      ⏸ Pause
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Job Details */}
          <div>
            {selectedJob ? (
              <div className="card" style={{ position: 'sticky', top: '20px' }}>
                <h3>Job Details</h3>

                <div className="form-group">
                  <label>Job ID</label>
                  <div className="text-muted">{selectedJob.job_id}</div>
                </div>

                <div className="form-group">
                  <label>Status</label>
                  <span className={`badge badge-${getJobStatusColor(selectedJob.status)}`}>
                    {getJobStatusLabel(selectedJob.status)}
                  </span>
                </div>

                <div className="form-group">
                  <label>Progress</label>
                  <MultiLevelProgress
                    detailedProgress={detailedProgress}
                    workProgress={selectedJob.progress || 0}
                  />
                </div>

                {/* Detailed Progress Info */}
                {detailedProgress && (
                  <div className="form-group">
                    <label>Translation Details</label>
                    <div style={{
                      padding: '12px',
                      background: '#f8f9fa',
                      borderRadius: '4px',
                      fontSize: '13px'
                    }}>
                      {detailedProgress.current_volume && (
                        <div style={{ marginBottom: '8px' }}>
                          <strong>Current Volume:</strong> {detailedProgress.current_volume}
                        </div>
                      )}
                      {detailedProgress.current_chapter && (
                        <div style={{ marginBottom: '8px' }}>
                          <strong>Current Chapter:</strong> {detailedProgress.current_chapter}
                        </div>
                      )}
                      {detailedProgress.total_chapters > 0 && (
                        <div style={{ marginBottom: '4px' }}>
                          Chapters: {detailedProgress.completed_chapters}/{detailedProgress.total_chapters}
                          ({((detailedProgress.completed_chapters / detailedProgress.total_chapters) * 100).toFixed(1)}%)
                        </div>
                      )}
                      {detailedProgress.total_blocks > 0 && (
                        <div>
                          Blocks: {detailedProgress.completed_blocks}/{detailedProgress.total_blocks}
                          ({((detailedProgress.completed_blocks / detailedProgress.total_blocks) * 100).toFixed(1)}%)
                        </div>
                      )}
                    </div>
                  </div>
                )}

                <div className="form-group">
                  <label>Works ({selectedJob.work_numbers.length})</label>
                  <div style={{ maxHeight: '150px', overflow: 'auto', padding: '10px', background: '#f8f9fa', borderRadius: '4px' }}>
                    {selectedJob.work_numbers.map(workNum => (
                      <div key={workNum} style={{ padding: '2px 0' }}>
                        {selectedJob.completed_works?.includes(workNum) && '✓ '}
                        {selectedJob.failed_works?.includes(workNum) && '✗ '}
                        {selectedJob.current_work === workNum && '⚙️ '}
                        {workNum}
                      </div>
                    ))}
                  </div>
                </div>

                <div className="form-group">
                  <label>Completed Works</label>
                  <div className="text-lg">
                    <span className="badge badge-success">
                      {selectedJob.completed_works?.length || 0}
                    </span>
                  </div>
                </div>

                <div className="form-group">
                  <label>Failed Works</label>
                  <div className="text-lg">
                    <span className="badge badge-danger">
                      {selectedJob.failed_works?.length || 0}
                    </span>
                  </div>
                </div>

                {selectedJob.start_time && (
                  <div className="form-group">
                    <label>Start Time</label>
                    <div className="text-muted text-sm">
                      {new Date(selectedJob.start_time).toLocaleString()}
                    </div>
                  </div>
                )}

                {selectedJob.end_time && (
                  <div className="form-group">
                    <label>End Time</label>
                    <div className="text-muted text-sm">
                      {new Date(selectedJob.end_time).toLocaleString()}
                    </div>
                  </div>
                )}

                {selectedJob.error_message && (
                  <div className="form-group">
                    <label>Error</label>
                    <div style={{ padding: '10px', background: '#fadbd8', borderRadius: '4px', fontSize: '14px' }}>
                      {selectedJob.error_message}
                    </div>
                  </div>
                )}

                {selectedJob.statistics && Object.keys(selectedJob.statistics).length > 0 && (
                  <div className="form-group">
                    <label>Statistics</label>
                    <div style={{ padding: '10px', background: '#f8f9fa', borderRadius: '4px', fontSize: '12px' }}>
                      <pre>{JSON.stringify(selectedJob.statistics, null, 2)}</pre>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="card empty-state">
                <p>Select a job to view details</p>
              </div>
            )}
          </div>
        </div>
        )
      )}
    </div>
  );
}

function getJobStatusColor(status) {
  switch (status) {
    case 'completed': return 'success';
    case 'running': return 'warning';
    case 'failed': return 'danger';
    case 'paused': return 'secondary';
    default: return 'info';
  }
}

function getJobStatusLabel(status) {
  switch (status) {
    case 'completed': return '✓ Completed';
    case 'running': return '⚙️ Running';
    case 'failed': return '✗ Failed';
    case 'paused': return '⏸ Paused';
    case 'queued': return '⏳ Queued';
    default: return status;
  }
}

function getProgressColor(percentage) {
  if (percentage === 100) return '#27ae60'; // Green - complete
  if (percentage >= 67) return '#3498db'; // Blue - almost done
  if (percentage >= 34) return '#f39c12'; // Yellow/orange - in progress
  return '#e74c3c'; // Red - just started
}

function getWorkflowStatusColor(status) {
  switch (status?.toLowerCase()) {
    case 'completed': return 'success';
    case 'running': return 'warning';
    case 'failed': return 'danger';
    case 'cancelled': return 'secondary';
    case 'pending': return 'info';
    case 'scheduled': return 'info';
    default: return 'secondary';
  }
}

function getWorkflowStatusLabel(status) {
  switch (status?.toLowerCase()) {
    case 'completed': return '✓ Completed';
    case 'running': return '⚙️ Running';
    case 'failed': return '✗ Failed';
    case 'cancelled': return '⏹ Cancelled';
    case 'pending': return '⏳ Pending';
    case 'scheduled': return '📅 Scheduled';
    default: return '○ Unknown';
  }
}

export default JobsPage;
