import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { worksAPI, jobsAPI, workflowAPI } from '../api/client';
import { showToast } from '../components/Toast';

function WorkListPage() {
  const navigate = useNavigate();
  const [works, setWorks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedWorks, setSelectedWorks] = useState(new Set());
  const [showModal, setShowModal] = useState(false);
  const [workStatuses, setWorkStatuses] = useState({}); // work_number -> { type, status, id, progress }
  const [loadingStatuses, setLoadingStatuses] = useState(false);
  const [useWorkflowSystem, setUseWorkflowSystem] = useState(true); // Default to workflow
  const [jobConfig, setJobConfig] = useState({
    model: 'gpt-4.1-nano',
    temperature: 0.3,
    max_retries: 3,
  });
  const [creating, setCreating] = useState(false);
  const [sortBy, setSortBy] = useState('directory_name');
  const [sortDirection, setSortDirection] = useState('asc');

  useEffect(() => {
    loadWorks();
    loadWorkStatuses();
  }, []);

  const loadWorks = async () => {
    try {
      setLoading(true);
      const data = await worksAPI.list(search);
      setWorks(data);
    } catch (error) {
      console.error('Failed to load works:', error);
      showToast('Failed to load works catalog', 'error');
    } finally {
      setLoading(false);
    }
  };

  const loadWorkStatuses = async () => {
    try {
      setLoadingStatuses(true);

      // Query both jobs and workflows
      const [jobs, workflows] = await Promise.all([
        jobsAPI.list().catch(() => []),
        workflowAPI.list(100).catch(() => [])
      ]);

      // Build status map
      const statusMap = {};

      // Add legacy jobs (lower priority)
      jobs.forEach(job => {
        if (job.work_numbers && Array.isArray(job.work_numbers)) {
          job.work_numbers.forEach(workNum => {
            statusMap[workNum] = {
              type: 'job',
              id: job.job_id,
              status: job.status,
              progress: job.progress || 0
            };
          });
        }
      });

      // Add workflows (higher priority - will override jobs)
      workflows.forEach(workflow => {
        if (workflow.work_id) {
          statusMap[workflow.work_id] = {
            type: 'workflow',
            id: workflow.flow_run_id,
            status: workflow.status,
            progress: workflow.overall_progress_pct || 0
          };
        }
      });

      setWorkStatuses(statusMap);
    } catch (error) {
      console.error('Failed to load work statuses:', error);
    } finally {
      setLoadingStatuses(false);
    }
  };

  const handleSearch = (e) => {
    e.preventDefault();
    loadWorks();
  };

  const toggleWorkSelection = (workNumber) => {
    const newSelection = new Set(selectedWorks);
    if (newSelection.has(workNumber)) {
      newSelection.delete(workNumber);
    } else {
      newSelection.add(workNumber);
    }
    setSelectedWorks(newSelection);
  };

  const selectAll = () => {
    setSelectedWorks(new Set(works.map(w => w.work_number)));
  };

  const clearSelection = () => {
    setSelectedWorks(new Set());
  };

  const formatCount = (count) => {
    if (!count) return '-';
    if (count < 1000) return count.toString();
    if (count < 1000000) return `${(count / 1000).toFixed(0)}K`;
    return `${(count / 1000000).toFixed(1)}M`;
  };

  const handleSort = (column) => {
    if (sortBy === column) {
      // Toggle direction if same column
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      // New column, default to ascending
      setSortBy(column);
      setSortDirection('asc');
    }
  };

  const getSortedWorks = () => {
    const sorted = [...works].sort((a, b) => {
      let aVal = a[sortBy];
      let bVal = b[sortBy];

      // Handle null/undefined values
      if (aVal == null) aVal = '';
      if (bVal == null) bVal = '';

      // Convert to string for consistent comparison
      if (typeof aVal === 'number') {
        return sortDirection === 'asc' ? aVal - bVal : bVal - aVal;
      }

      // String comparison
      const comparison = aVal.toString().localeCompare(bVal.toString(), 'zh-CN');
      return sortDirection === 'asc' ? comparison : -comparison;
    });

    return sorted;
  };

  const SortableHeader = ({ column, children, align }) => (
    <th
      style={{ cursor: 'pointer', textAlign: align, userSelect: 'none' }}
      onClick={() => handleSort(column)}
    >
      {children}
      {sortBy === column && (
        <span style={{ marginLeft: '5px' }}>
          {sortDirection === 'asc' ? '▲' : '▼'}
        </span>
      )}
    </th>
  );

  const viewProgress = (workNumber) => {
    const status = workStatuses[workNumber];
    if (!status) return;

    if (status.type === 'workflow') {
      navigate(`/jobs?workflow_id=${status.id}`);
    } else {
      navigate(`/jobs?job_id=${status.id}`);
    }
  };

  const startTranslationForWork = async (workNumber) => {
    const work = works.find(w => w.work_number === workNumber);
    if (!work) return;

    setSelectedWorks(new Set([workNumber]));
    setShowModal(true);
  };

  const createTranslationJob = async () => {
    if (selectedWorks.size === 0) {
      showToast('Please select at least one work to translate', 'warning');
      return;
    }

    try {
      setCreating(true);

      if (useWorkflowSystem && selectedWorks.size === 1) {
        // Use new workflow system for single work
        const workId = Array.from(selectedWorks)[0];
        const workflow = await workflowAPI.start(workId, null, jobConfig, false);

        clearSelection();
        setShowModal(false);
        loadWorkStatuses(); // Refresh statuses

        showToast(`Workflow started! Navigating to jobs page...`, 'success', 3000);
        navigate(`/jobs?workflow_id=${workflow.flow_run_id}`);
      } else {
        // Use legacy job system for bulk or if workflow disabled
        const workNumbers = Array.from(selectedWorks);
        const job = await jobsAPI.create(workNumbers, jobConfig);

        clearSelection();
        setShowModal(false);
        loadWorkStatuses(); // Refresh statuses

        showToast(`Translation job created! Navigating to jobs page...`, 'success', 3000);
        navigate(`/jobs?job_id=${job.job_id}`);
      }
    } catch (error) {
      console.error('Failed to create translation:', error);
      showToast(`Failed to create translation: ${error.message || 'Unknown error'}`, 'error');
    } finally {
      setCreating(false);
    }
  };

  if (loading) {
    return (
      <div className="empty-state">
        <div className="spinner"></div>
        <p>Loading works catalog...</p>
      </div>
    );
  }

  return (
    <div>
      {/* Search and Actions */}
      <div className="card mb-2">
        <form onSubmit={handleSearch} className="flex-between">
          <div className="flex flex-gap" style={{ flex: 1 }}>
            <input
              type="text"
              className="input"
              placeholder="Search by title, author, or work number..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ flex: 1 }}
            />
            <button type="submit" className="btn btn-primary">Search</button>
          </div>
        </form>
      </div>

      {/* Selection Actions */}
      {selectedWorks.size > 0 && (
        <div className="card mb-2" style={{ background: '#e8f4f8' }}>
          <div className="flex-between">
            <div>
              <strong>{selectedWorks.size}</strong> work(s) selected
            </div>
            <div className="flex flex-gap">
              <button className="btn btn-secondary" onClick={clearSelection}>
                Clear Selection
              </button>
              <button className="btn btn-success" onClick={() => setShowModal(true)}>
                ▶️ Start Translation
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bulk Actions */}
      <div className="flex-between mb-2">
        <div className="text-muted">
          {works.length} works found
        </div>
        <button className="btn btn-secondary" onClick={selectAll}>
          Select All
        </button>
      </div>

      {/* Works Table */}
      {works.length === 0 ? (
        <div className="empty-state">
          <h3>No works found</h3>
          <p>Try adjusting your search query</p>
        </div>
      ) : (
        <div className="card">
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: '40px' }}>
                  <input
                    type="checkbox"
                    checked={selectedWorks.size === works.length && works.length > 0}
                    onChange={() => selectedWorks.size === works.length ? clearSelection() : selectAll()}
                  />
                </th>
                <SortableHeader column="directory_name">Directory</SortableHeader>
                <SortableHeader column="work_number">Work #</SortableHeader>
                <SortableHeader column="title_chinese">Title (Chinese)</SortableHeader>
                <SortableHeader column="title_english">Title (English)</SortableHeader>
                <SortableHeader column="author_chinese">Author (Chinese)</SortableHeader>
                <SortableHeader column="author_english">Author (English)</SortableHeader>
                <SortableHeader column="total_volumes" align="center">Volumes</SortableHeader>
                <SortableHeader column="character_count" align="right">Characters</SortableHeader>
                <SortableHeader column="word_count" align="right">Words</SortableHeader>
                <SortableHeader column="estimated_tokens" align="right">Est. Tokens</SortableHeader>
                <th>Translation Status</th>
                <th style={{ width: '150px' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {getSortedWorks().map((work) => (
                <tr key={work.work_number} onClick={() => toggleWorkSelection(work.work_number)}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selectedWorks.has(work.work_number)}
                      onChange={() => toggleWorkSelection(work.work_number)}
                      onClick={(e) => e.stopPropagation()}
                    />
                  </td>
                  <td className="text-muted"><small>{work.directory_name || '-'}</small></td>
                  <td><strong>{work.work_number}</strong></td>
                  <td>{work.title_chinese}</td>
                  <td className="text-muted">{work.title_english || '-'}</td>
                  <td>{work.author_chinese}</td>
                  <td className="text-muted">{work.author_english || '-'}</td>
                  <td style={{ textAlign: 'center' }}>
                    <span className="badge badge-info">{work.total_volumes}</span>
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <small className="text-muted">{formatCount(work.character_count)}</small>
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <small className="text-muted">{formatCount(work.word_count)}</small>
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <small className="text-muted">{formatCount(work.estimated_tokens)}</small>
                  </td>
                  <td>
                    {workStatuses[work.work_number] ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        <span className={`badge badge-${getWorkflowStatusColor(workStatuses[work.work_number].status)}`}>
                          {getWorkflowStatusLabel(workStatuses[work.work_number].status)}
                        </span>
                        {workStatuses[work.work_number].progress > 0 && (
                          <div className="text-sm text-muted">
                            {workStatuses[work.work_number].progress.toFixed(0)}%
                          </div>
                        )}
                        <span className="badge badge-secondary text-xs">
                          {workStatuses[work.work_number].type === 'workflow' ? '⚡ Workflow' : '⚙️ Job'}
                        </span>
                      </div>
                    ) : (
                      <span className="badge badge-secondary">○ Not Started</span>
                    )}
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    {workStatuses[work.work_number] ? (
                      <button
                        className="btn btn-sm btn-primary"
                        onClick={() => viewProgress(work.work_number)}
                        style={{ width: '100%' }}
                      >
                        📊 View Progress
                      </button>
                    ) : (
                      <button
                        className="btn btn-sm btn-success"
                        onClick={() => startTranslationForWork(work.work_number)}
                        style={{ width: '100%' }}
                      >
                        ▶️ Translate
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create Job Modal */}
      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Start Translation</h2>

            <div className="form-group">
              <label>Selected Works ({selectedWorks.size})</label>
              <div style={{ maxHeight: '150px', overflow: 'auto', padding: '10px', background: '#f8f9fa', borderRadius: '4px' }}>
                {Array.from(selectedWorks).map(workNum => {
                  const work = works.find(w => w.work_number === workNum);
                  return (
                    <div key={workNum} style={{ padding: '5px 0' }}>
                      <strong>{workNum}</strong>: {work?.title_chinese}
                    </div>
                  );
                })}
              </div>
            </div>

            {selectedWorks.size === 1 && (
              <div className="form-group">
                <label>Translation System</label>
                <select
                  className="select"
                  value={useWorkflowSystem ? 'workflow' : 'job'}
                  onChange={(e) => setUseWorkflowSystem(e.target.value === 'workflow')}
                  style={{ width: '100%' }}
                >
                  <option value="workflow">⚡ Workflow System (Recommended - 7 stage pipeline with footnotes)</option>
                  <option value="job">⚙️ Legacy Job System (Simple translation)</option>
                </select>
                <span className="help-text">
                  Workflow system provides stage-by-stage processing, cultural footnotes, and AI-powered cleanup.
                </span>
              </div>
            )}

            {selectedWorks.size > 1 && (
              <div className="alert alert-info" style={{ padding: '10px', background: '#e8f4f8', borderRadius: '4px', marginBottom: '12px' }}>
                <strong>Note:</strong> Bulk translation will use the legacy job system. For workflow features, please translate works individually.
              </div>
            )}

            <div className="form-group">
              <label>Translation Model</label>
              <select
                className="select"
                value={jobConfig.model}
                onChange={(e) => setJobConfig({ ...jobConfig, model: e.target.value })}
                style={{ width: '100%' }}
              >
                <option value="gpt-4.1-nano">GPT-4.1 Nano (Default, Fast, Cost-Effective)</option>
                <option value="gpt-4o-mini">GPT-4o Mini</option>
                <option value="gpt-4o">GPT-4o (Best Quality)</option>
                <option value="gpt-4-turbo">GPT-4 Turbo</option>
              </select>
            </div>

            <div className="form-group">
              <label>Temperature</label>
              <input
                type="number"
                className="input"
                min="0"
                max="1"
                step="0.1"
                value={jobConfig.temperature}
                onChange={(e) => setJobConfig({ ...jobConfig, temperature: parseFloat(e.target.value) })}
              />
              <span className="help-text">Lower = more consistent, Higher = more creative</span>
            </div>

            <div className="form-group">
              <label>Max Retries</label>
              <input
                type="number"
                className="input"
                min="1"
                max="10"
                value={jobConfig.max_retries}
                onChange={(e) => setJobConfig({ ...jobConfig, max_retries: parseInt(e.target.value) })}
              />
              <span className="help-text">Number of retry attempts for failed translations</span>
            </div>

            <div className="flex flex-gap mt-2">
              <button
                className="btn btn-success"
                onClick={createTranslationJob}
                disabled={creating}
                style={{ flex: 1 }}
              >
                {creating ? 'Creating...' : '▶️ Start Translation'}
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => setShowModal(false)}
                disabled={creating}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Helper functions for workflow status display
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
    case 'queued': return '⏳ Queued';
    default: return '○ Unknown';
  }
}

// Legacy functions for backward compatibility
function getStatusColor(status) {
  switch (status) {
    case 'completed': return 'success';
    case 'in_progress': return 'warning';
    case 'failed': return 'danger';
    default: return 'secondary';
  }
}

function getStatusLabel(status) {
  switch (status) {
    case 'completed': return '✓ Completed';
    case 'in_progress': return '⚙️ In Progress';
    case 'failed': return '✗ Failed';
    default: return '○ Not Started';
  }
}

export default WorkListPage;
