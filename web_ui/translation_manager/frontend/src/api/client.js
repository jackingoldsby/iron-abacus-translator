import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Works API
export const worksAPI = {
  // List all works with optional search
  list: async (search = '') => {
    const response = await api.get('/api/works', {
      params: search ? { search } : {}
    });
    return response.data;
  },

  // Get detailed work information
  get: async (workNumber) => {
    const response = await api.get(`/api/works/${workNumber}`);
    return response.data;
  },
};

// Jobs API
export const jobsAPI = {
  // Create a new translation job
  create: async (workNumbers, config = {}) => {
    const response = await api.post('/api/jobs', {
      work_numbers: workNumbers,
      model: config.model || 'gpt-4.1-nano',
      temperature: config.temperature || 0.3,
      max_retries: config.max_retries || 3,
      output_dir: config.output_dir || null,
    });
    return response.data;
  },

  // List all jobs
  list: async () => {
    const response = await api.get('/api/jobs');
    return response.data;
  },

  // Get job status
  get: async (jobId) => {
    const response = await api.get(`/api/jobs/${jobId}`);
    return response.data;
  },

  // Cancel a job (pause) or delete permanently
  cancel: async (jobId, permanent = false) => {
    const params = permanent ? { permanent: true } : {};
    const response = await api.delete(`/api/jobs/${jobId}`, { params });
    return response.data;
  },

  // Get detailed progress for a job's current work
  getDetailedProgress: async (jobId) => {
    const response = await api.get(`/api/jobs/${jobId}/progress`);
    return response.data;
  },
};

// Progress API
export const progressAPI = {
  // Get detailed progress for a work/volume
  get: async (workNumber, volume = null) => {
    const params = volume ? { volume } : {};
    const response = await api.get(`/api/progress/${workNumber}`, { params });
    return response.data;
  },
};

// Workflow API
export const workflowAPI = {
  // List workflow templates
  listTemplates: async () => {
    const response = await api.get('/api/workflow/workflows');
    return response.data;
  },

  // Get specific workflow template
  getTemplate: async (workflowId) => {
    const response = await api.get(`/api/workflow/workflows/${workflowId}`);
    return response.data;
  },

  // Start a new workflow
  start: async (workflowId, workId, volume = null, config = {}, resume = false) => {
    const response = await api.post('/api/workflow/start', {
      workflow_id: workflowId,
      work_id: workId,
      volume: volume,
      config: config,
      resume: resume,
    });
    return response.data;
  },

  // Get workflow status
  getStatus: async (flowRunId) => {
    const response = await api.get(`/api/workflow/status/${flowRunId}`);
    return response.data;
  },

  // List workflows
  list: async (limit = 50, status = null) => {
    const params = { limit };
    if (status) params.status = status;
    const response = await api.get('/api/workflow/list', { params });
    return response.data;
  },

  // Cancel workflow and optionally delete all files
  cancel: async (flowRunId, deleteFiles = false) => {
    const params = deleteFiles ? { delete_files: true } : {};
    const response = await api.delete(`/api/workflow/${flowRunId}`, { params });
    return response.data;
  },

  // Pause a workflow
  pause: async (flowRunId) => {
    const response = await api.post(`/api/workflow/pause/${flowRunId}`);
    return response.data;
  },

  // Resume a paused workflow
  resume: async (flowRunId) => {
    const response = await api.post(`/api/workflow/resume/${flowRunId}`);
    return response.data;
  },

  // Rollback workflow to a specific stage
  rollback: async (flowRunId, targetStage) => {
    const response = await api.post(`/api/workflow/rollback/${flowRunId}`, null, {
      params: { target_stage: targetStage }
    });
    return response.data;
  },

  // Delete results for a specific stage
  deleteStage: async (flowRunId, stageNum) => {
    const response = await api.delete(`/api/workflow/stage/${flowRunId}/${stageNum}`);
    return response.data;
  },

  // Delete all workflow results
  deleteAll: async (flowRunId) => {
    const response = await api.delete(`/api/workflow/all/${flowRunId}`);
    return response.data;
  },

  // Get workflow artifacts
  getArtifacts: async (flowRunId) => {
    const response = await api.get(`/api/workflow/artifacts/${flowRunId}`);
    return response.data;
  },

  // Get detailed task logs (includes OpenAI responses, translation progress, etc.)
  getLogs: async (flowRunId, limit = 200, offset = 0) => {
    const response = await api.get(`/api/workflow/logs/${flowRunId}`, {
      params: { limit, offset }
    });
    return response.data;
  },

  // Connect to SSE stream for real-time updates
  streamProgress: (flowRunId, onMessage, onError = null) => {
    const url = `${API_BASE_URL}/api/workflow/stream/${flowRunId}`;
    const eventSource = new EventSource(url);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch (e) {
        console.error('Failed to parse SSE message:', e);
      }
    };

    eventSource.onerror = (error) => {
      console.error('SSE error:', error);
      if (onError) onError(error);
      eventSource.close();
    };

    return eventSource; // Return so caller can close it
  },
};

// DAG Pipeline API
export const dagAPI = {
  // Get V2 pipeline definition
  getPipeline: async (version = 'v2') => {
    const path = version === 'v1' ? '/api/dag/pipeline/v1' : '/api/dag/pipeline';
    const response = await api.get(path);
    return response.data;
  },

  // Start a DAG run
  startRun: async (workId, volumes = [], pipelineVersion = 'v2', config = {}) => {
    const response = await api.post('/api/dag/run', {
      work_id: workId,
      volumes,
      pipeline_version: pipelineVersion,
      config,
    });
    return response.data;
  },

  // Get DAG run status
  getRun: async (runId) => {
    const response = await api.get(`/api/dag/run/${runId}`);
    return response.data;
  },

  // Stream real-time node updates via SSE
  streamRun: (runId, onMessage, onError = null) => {
    const url = `${API_BASE_URL}/api/dag/run/${runId}/stream`;
    const eventSource = new EventSource(url);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch (e) {
        console.error('Failed to parse DAG SSE message:', e);
      }
    };

    eventSource.onerror = (error) => {
      console.error('DAG SSE error:', error);
      if (onError) onError(error);
      eventSource.close();
    };

    return eventSource;
  },

  // Validate a node's output
  validateNode: async (runId, nodeId) => {
    const response = await api.post(`/api/dag/run/${runId}/validate/${nodeId}`);
    return response.data;
  },

  // Retry a failed node
  retryNode: async (runId, nodeId) => {
    const response = await api.post(`/api/dag/run/${runId}/retry/${nodeId}`);
    return response.data;
  },

  // Skip a node
  skipNode: async (runId, nodeId) => {
    const response = await api.post(`/api/dag/run/${runId}/skip/${nodeId}`);
    return response.data;
  },

  // List DAG runs
  listRuns: async (workId = null, status = null, limit = 50) => {
    const params = { limit };
    if (workId) params.work_id = workId;
    if (status) params.status = status;
    const response = await api.get('/api/dag/runs', { params });
    return response.data;
  },
};

// Authors API
export const authorsAPI = {
  list: async () => {
    const response = await api.get('/api/authors');
    return response.data;
  },
};

// Works volumes API
export const volumesAPI = {
  get: async (workNumber) => {
    const response = await api.get(`/api/works/${workNumber}/volumes`);
    return response.data;
  },
};

// Batch Run API
export const batchAPI = {
  // Start a batch workflow run
  start: async (workflowId, workIds, config = {}) => {
    const response = await api.post('/api/workflow/runs/batch', {
      workflow_id: workflowId,
      work_ids: workIds,
      config: config,
    });
    return response.data;
  },

  // List batch runs
  list: async (limit = 50) => {
    const response = await api.get('/api/workflow/batch-runs', {
      params: { limit }
    });
    return response.data;
  },

  // Get batch run details
  get: async (batchId) => {
    const response = await api.get(`/api/workflow/batch-runs/${batchId}`);
    return response.data;
  },
};

// WebSocket connection
export class JobWebSocket {
  constructor(onMessage) {
    this.ws = null;
    this.onMessage = onMessage;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
  }

  connect() {
    const wsUrl = API_BASE_URL.replace('http', 'ws') + '/ws';
    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      console.log('WebSocket connected');
      this.reconnectAttempts = 0;
      // Send ping every 30 seconds to keep connection alive
      this.pingInterval = setInterval(() => {
        if (this.ws.readyState === WebSocket.OPEN) {
          this.ws.send('ping');
        }
      }, 30000);
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.onMessage(data);
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    this.ws.onclose = () => {
      console.log('WebSocket disconnected');
      clearInterval(this.pingInterval);

      // Attempt to reconnect
      if (this.reconnectAttempts < this.maxReconnectAttempts) {
        this.reconnectAttempts++;
        console.log(`Reconnecting... (attempt ${this.reconnectAttempts})`);
        setTimeout(() => this.connect(), 3000);
      }
    };
  }

  disconnect() {
    if (this.ws) {
      clearInterval(this.pingInterval);
      this.ws.close();
      this.ws = null;
    }
  }
}

export default api;
