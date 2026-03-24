import React, { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { jobsAPI, workflowAPI, worksAPI } from '../api/client';
import { showToast } from '../components/Toast';
import Tooltip from '../components/Tooltip';
import {
  formatRelativeTime,
  formatFullTimestamp,
  formatDuration,
  calculateETA,
  getETAColorClass
} from '../utils/timeFormatting';
import './AllJobsPage.css';

/**
 * AllJobsPage Component
 *
 * Unified view showing all jobs (workflows + legacy) across all works
 * Features:
 * - Combined list of workflows and legacy jobs
 * - Work filter dropdown
 * - Job type badges
 * - Click to navigate to detail view
 */
function AllJobsPage() {
  const navigate = useNavigate();
  const [workflows, setWorkflows] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedWorkFilter, setSelectedWorkFilter] = useState('all');
  const [workMetadata, setWorkMetadata] = useState({}); // Cache for work title/author

  console.log('[AllJobsPage] Rendering with:', {
    workflows: workflows.length,
    jobs: jobs.length,
    loading
  });

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      console.log('[AllJobsPage] Loading data...');
      setLoading(true);
      const [workflowData, jobData] = await Promise.all([
        workflowAPI.list(100),
        jobsAPI.list()
      ]);
      console.log('[AllJobsPage] Data loaded:', {
        workflows: workflowData?.length || 0,
        jobs: jobData?.length || 0
      });
      setWorkflows(workflowData || []);
      setJobs(jobData || []);

      // Fetch work metadata for all unique work IDs
      await loadWorkMetadata(workflowData, jobData);
    } catch (error) {
      console.error('[AllJobsPage] Failed to load jobs:', error);
      showToast('Failed to load jobs', 'error');
    } finally {
      setLoading(false);
    }
  };

  // Load work metadata (title/author) for all works
  const loadWorkMetadata = async (workflowData, jobData) => {
    const workIds = new Set();

    // Collect work IDs from workflows
    workflowData?.forEach(wf => {
      if (wf.work_id) workIds.add(wf.work_id);
    });

    // Collect work IDs from legacy jobs
    jobData?.forEach(job => {
      if (job.work_numbers && Array.isArray(job.work_numbers)) {
        job.work_numbers.forEach(workId => workIds.add(workId));
      }
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

  // Combine workflows and legacy jobs into unified list
  // Batch jobs appear multiple times (once per work_id)
  const allJobs = useMemo(() => {
    const combined = [];

    // Add workflows
    workflows.forEach(wf => {
      const metadata = workMetadata[wf.work_id];
      combined.push({
        type: 'workflow',
        id: wf.flow_run_id,
        work_id: wf.work_id,
        volume: wf.volume,
        status: wf.status,
        progress: wf.overall_progress_pct || 0,
        start_time: wf.start_time,
        end_time: wf.end_time,
        duration: wf.duration_seconds,
        current_stage: wf.current_stage,
        error: wf.error_message,
        workflow_id: wf.workflow_id,
        workflow_name: wf.workflow_name,
        // Add metadata
        title_english: metadata?.title_english,
        title_chinese: metadata?.title_chinese,
        author_english: metadata?.author_english,
        author_chinese: metadata?.author_chinese,
        raw: wf // Keep original for detail navigation
      });
    });

    // Add legacy jobs (expand batch jobs to one entry per work)
    jobs.forEach(job => {
      const workNumbers = job.work_numbers || [];
      workNumbers.forEach(workId => {
        const metadata = workMetadata[workId];
        combined.push({
          type: 'legacy',
          id: job.job_id,
          work_id: workId,
          status: job.status,
          progress: job.progress || 0,
          start_time: job.start_time,
          end_time: job.end_time,
          current_work: job.current_work,
          completed_count: job.completed_works?.length || 0,
          failed_count: job.failed_works?.length || 0,
          is_batch: workNumbers.length > 1,
          // Add metadata
          title_english: metadata?.title_english,
          title_chinese: metadata?.title_chinese,
          author_english: metadata?.author_english,
          author_chinese: metadata?.author_chinese,
          raw: job // Keep original for detail navigation
        });
      });
    });

    // Sort by start_time (newest first)
    return combined.sort((a, b) => {
      const timeA = new Date(a.start_time || 0);
      const timeB = new Date(b.start_time || 0);
      return timeB - timeA;
    });
  }, [workflows, jobs, workMetadata]);

  // Filter jobs based on selected work
  const filteredJobs = useMemo(() => {
    if (selectedWorkFilter === 'all') return allJobs;
    return allJobs.filter(job => job.work_id === selectedWorkFilter);
  }, [allJobs, selectedWorkFilter]);

  // Get count for each work ID (for dropdown display)
  const workCounts = useMemo(() => {
    const counts = {};
    uniqueWorkIds.forEach(workId => {
      if (workId === 'all') {
        counts[workId] = allJobs.length;
      } else {
        counts[workId] = allJobs.filter(job => job.work_id === workId).length;
      }
    });
    return counts;
  }, [uniqueWorkIds, allJobs]);

  const handleJobClick = (job) => {
    if (job.type === 'workflow') {
      navigate(`/jobs?workflow_id=${job.id}`);
    } else {
      navigate(`/jobs?job_id=${job.id}`);
    }
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'completed': return 'success';
      case 'running': return 'primary';
      case 'failed': return 'danger';
      case 'paused': return 'warning';
      case 'queued':
      case 'scheduled':
      case 'pending': return 'secondary';
      default: return 'secondary';
    }
  };

  const getStatusLabel = (status) => {
    return status.charAt(0).toUpperCase() + status.slice(1);
  };

  // Get selected work details (must be before any conditional returns)
  const selectedWorkDetails = useMemo(() => {
    if (selectedWorkFilter === 'all') return null;

    // Find a job with this work_id to get details
    const job = allJobs.find(j => j.work_id === selectedWorkFilter);
    if (!job) return null;

    const metadata = workMetadata[selectedWorkFilter];

    return {
      work_id: selectedWorkFilter,
      title: metadata?.title_english || metadata?.title_chinese || `Work ${selectedWorkFilter}`,
      author: metadata?.author_english || metadata?.author_chinese || 'Unknown Author',
      jobCount: workCounts[selectedWorkFilter] || 0
    };
  }, [selectedWorkFilter, allJobs, workCounts, workMetadata]);

  if (loading) {
    return (
      <div className="empty-state">
        <div className="spinner"></div>
        <p>Loading all jobs...</p>
      </div>
    );
  }

  return (
    <div className="all-jobs-page-layout">
      {/* Left Sidebar - Work Selector */}
      <div className="jobs-sidebar">
        <div className="sidebar-header">
          <h3>📚 Select Work</h3>
          <button className="btn btn-sm btn-secondary" onClick={() => navigate('/jobs')}>
            ← Back
          </button>
        </div>

        <div className="work-list">
          {/* All Works Option */}
          <div
            className={`work-item ${selectedWorkFilter === 'all' ? 'active' : ''}`}
            onClick={() => setSelectedWorkFilter('all')}
          >
            <div className="work-item-header">
              <span className="work-id">All Works</span>
              <span className="work-count">{workCounts['all']}</span>
            </div>
          </div>

          <div className="work-divider"></div>

          {/* Individual Works */}
          {uniqueWorkIds.filter(id => id !== 'all').map(workId => {
            const metadata = workMetadata[workId];
            const title = metadata?.title_english || metadata?.title_chinese || workId;
            return (
              <div
                key={workId}
                className={`work-item ${selectedWorkFilter === workId ? 'active' : ''}`}
                onClick={() => setSelectedWorkFilter(workId)}
              >
                <div className="work-item-header">
                  <span className="work-id">{workId}</span>
                  <span className="work-count">{workCounts[workId]}</span>
                </div>
                {metadata && (
                  <div className="work-item-details">
                    <div className="work-title-small">{title}</div>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div className="sidebar-footer">
          <button className="btn btn-primary btn-block" onClick={loadData}>
            🔄 Refresh All
          </button>
        </div>
      </div>

      {/* Right Content - Work Details & Jobs */}
      <div className="jobs-content">
        {/* Work Details Header */}
        {selectedWorkDetails && (
          <div className="work-details-header">
            <div className="work-info">
              <h2>{selectedWorkDetails.title}</h2>
              <p className="work-author">by {selectedWorkDetails.author}</p>
              <p className="work-meta">
                <span className="badge badge-primary">{selectedWorkDetails.work_id}</span>
                <span className="text-muted" style={{ marginLeft: '12px' }}>
                  {selectedWorkDetails.jobCount} job{selectedWorkDetails.jobCount !== 1 ? 's' : ''}
                </span>
              </p>
            </div>
          </div>
        )}

        {!selectedWorkDetails && (
          <div className="work-details-header">
            <div className="work-info">
              <h2>All Translation Jobs</h2>
              <p className="work-meta">
                <span className="text-muted">
                  Showing all jobs across {uniqueWorkIds.length - 1} work{uniqueWorkIds.length !== 2 ? 's' : ''}
                </span>
              </p>
            </div>
          </div>
        )}

        {/* Jobs Table */}
        {filteredJobs.length === 0 ? (
          <div className="empty-state">
            <h3>No jobs {selectedWorkFilter !== 'all' ? `for ${selectedWorkFilter}` : ''}</h3>
            <p>Go to Works Catalog to start a translation job</p>
          </div>
        ) : (
          <div className="card">
            <table className="jobs-table">
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Work</th>
                  <th>Status</th>
                  <th>Progress</th>
                  <th>Started</th>
                  <th>Duration</th>
                  <th>ETA</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {filteredJobs.map((job, index) => {
                  const title = job.title_english || job.title_chinese || job.work_id;
                  const author = job.author_english || job.author_chinese || '';
                  const eta = calculateETA(job.progress, job.duration, job.status);
                  const etaColorClass = getETAColorClass(job.progress, job.duration);

                  // Prepare tooltip content
                  const tooltipContent = (
                    <div>
                      <h4>{title}</h4>
                      {author && <p><span className="label">by</span> <span className="value">{author}</span></p>}
                      <hr />
                      <p><span className="label">Work ID:</span> <span className="value"><code>{job.work_id}</code></span></p>
                      {job.volume && <p><span className="label">Volume:</span> <span className="value">{job.volume}</span></p>}
                      {job.workflow_name && <p><span className="label">Workflow:</span> <span className="value">{job.workflow_name}</span></p>}
                      <hr />
                      <p><span className="label">Started:</span> <span className="value">{formatFullTimestamp(job.start_time)}</span></p>
                      <p><span className="label">Elapsed:</span> <span className="value">{formatDuration(job.duration)}</span></p>
                      {job.status === 'running' && <p><span className="label">ETA:</span> <span className="value">{eta}</span></p>}
                      {job.current_stage && <p><span className="label">Stage:</span> <span className="value">{job.current_stage}</span></p>}
                    </div>
                  );

                  return (
                    <tr
                      key={`${job.type}-${job.id}-${job.work_id}-${index}`}
                      onClick={() => handleJobClick(job)}
                      style={{ cursor: 'pointer' }}
                      className="job-row">
                      {/* Type Badge */}
                      <td>
                        <span className={`badge badge-${job.type === 'workflow' ? 'primary' : 'secondary'}`}>
                          {job.type === 'workflow' ? '⚡' : '⚙️'}
                        </span>
                        {job.is_batch && (
                          <span className="badge badge-info" style={{ marginLeft: '4px' }} title="Batch job with multiple works">
                            📦
                          </span>
                        )}
                      </td>

                      {/* Work (with Tooltip) */}
                      <td>
                        <Tooltip content={tooltipContent}>
                          <div>
                            <div><strong>{job.work_id}</strong>{job.volume && <span className="text-muted"> (Vol {job.volume})</span>}</div>
                            <div className="text-sm text-muted" style={{ marginTop: '2px' }}>{title}</div>
                            {author && <div className="text-xs text-muted">by {author}</div>}
                          </div>
                        </Tooltip>
                      </td>

                      {/* Status */}
                      <td>
                        <span className={`badge badge-${getStatusColor(job.status)}`}>
                          {getStatusLabel(job.status)}
                        </span>
                      </td>

                      {/* Progress */}
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <div className="progress-bar-mini" style={{ flex: 1, maxWidth: '100px' }}>
                            <div
                              className="progress-fill-mini"
                              style={{
                                width: `${job.progress}%`,
                                backgroundColor: job.status === 'completed' ? '#4CAF50' : '#2196F3'
                              }}
                            />
                          </div>
                          <span className="text-sm">{job.progress.toFixed(0)}%</span>
                        </div>
                      </td>

                      {/* Started (Relative Time) */}
                      <td className="text-sm text-muted" title={formatFullTimestamp(job.start_time)}>
                        {formatRelativeTime(job.start_time)}
                      </td>

                      {/* Duration */}
                      <td className="text-sm">
                        {formatDuration(job.duration)}
                      </td>

                      {/* ETA */}
                      <td className={`text-sm ${etaColorClass}`}>
                        {eta}
                      </td>

                      {/* Details */}
                      <td className="text-sm text-muted">
                        {job.type === 'workflow' && job.current_stage && (
                          <span>{job.current_stage}</span>
                        )}
                        {job.type === 'legacy' && job.current_work && (
                          <span>{job.current_work}</span>
                        )}
                        {job.type === 'legacy' && (
                          <div style={{ marginTop: '4px' }}>
                            <span className="badge badge-success" style={{ fontSize: '10px' }}>
                              ✓ {job.completed_count}
                            </span>
                            {job.failed_count > 0 && (
                              <span className="badge badge-danger" style={{ fontSize: '10px', marginLeft: '4px' }}>
                                ✗ {job.failed_count}
                              </span>
                            )}
                          </div>
                        )}
                        {job.error && (
                          <div className="text-danger" style={{ marginTop: '4px', fontSize: '11px' }}>
                            {job.error.substring(0, 50)}{job.error.length > 50 && '...'}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Summary Stats */}
        <div className="stats-summary" style={{ marginTop: '16px', display: 'flex', gap: '16px' }}>
          <div className="stat-card">
            <div className="stat-label">Total Jobs</div>
            <div className="stat-value">{filteredJobs.length}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Workflows</div>
            <div className="stat-value">
              {filteredJobs.filter(j => j.type === 'workflow').length}
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Legacy Jobs</div>
            <div className="stat-value">
              {filteredJobs.filter(j => j.type === 'legacy').length}
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Running</div>
            <div className="stat-value">
              {filteredJobs.filter(j => j.status === 'running').length}
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Completed</div>
            <div className="stat-value">
              {filteredJobs.filter(j => j.status === 'completed').length}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default AllJobsPage;
