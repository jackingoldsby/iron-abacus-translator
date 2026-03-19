import React, { useState, useEffect, useRef } from 'react';
import { workflowAPI } from '../api/client';
import './WorkflowTerminal.css';

/**
 * WorkflowTerminal Component
 *
 * Terminal-style log viewer for real-time workflow updates.
 * Displays streaming messages from the workflow without page refreshes.
 *
 * Props:
 * - flowRunId: The workflow run ID to stream logs from
 * - workflowStatus: Real-time workflow status from parent (via SSE)
 * - maxLines: Maximum number of log lines to display (default: 100)
 * - height: Terminal height in pixels (default: 300)
 */
function WorkflowTerminal({ flowRunId, workflowStatus, maxLines = 100, height = 300 }) {
  const [logs, setLogs] = useState([]);
  const [detailedLogs, setDetailedLogs] = useState([]);
  const terminalRef = useRef(null);
  const autoScrollRef = useRef(true);
  const previousStatusRef = useRef(null);
  const logsIntervalRef = useRef(null);

  // Watch for workflow status changes and generate log entries
  useEffect(() => {
    if (!workflowStatus) {
      if (logs.length === 0) {
        addLog('info', '⏳ Waiting for workflow updates...');
      }
      return;
    }

    const prevStatus = previousStatusRef.current;

    // Deep comparison: skip if nothing actually changed
    if (prevStatus) {
      const statusChanged = prevStatus.status !== workflowStatus.status;
      const stageChanged = prevStatus.current_stage !== workflowStatus.current_stage;
      const progressChanged = Math.floor((prevStatus.overall_progress_pct || 0) / 5) !==
                             Math.floor((workflowStatus.overall_progress_pct || 0) / 5);
      const stagesChanged = JSON.stringify(prevStatus.stages) !==
                           JSON.stringify(workflowStatus.stages);

      // Skip update if nothing changed
      if (!statusChanged && !stageChanged && !progressChanged && !stagesChanged) {
        return;
      }
    }

    // Log status changes
    if (!prevStatus || prevStatus.status !== workflowStatus.status) {
      addLog('status', `📍 Workflow: ${workflowStatus.status.toUpperCase()}`);
    }

    // Log stage changes
    if (!prevStatus || prevStatus.current_stage !== workflowStatus.current_stage) {
      if (workflowStatus.current_stage) {
        addLog('status', `📍 Current Stage: ${workflowStatus.current_stage}`);
      }
    }

    // Log progress updates (only on significant changes)
    if (workflowStatus.overall_progress_pct !== undefined) {
      const prevPct = prevStatus?.overall_progress_pct || 0;
      const currentPct = workflowStatus.overall_progress_pct;
      // Log every 5% change or completion
      if (Math.floor(currentPct / 5) > Math.floor(prevPct / 5) || currentPct === 100) {
        addLog('progress', `⏳ Progress: ${currentPct.toFixed(1)}%`);
      }
    }

    // Log stage-specific updates
    if (workflowStatus.stages && Array.isArray(workflowStatus.stages)) {
      workflowStatus.stages.forEach(stage => {
        const prevStage = prevStatus?.stages?.find(s => s.stage_number === stage.stage_number);

        // Log stage status changes
        if (!prevStage || prevStage.status !== stage.status) {
          if (stage.status === 'running') {
            addLog('stage', `▶️  Stage ${stage.stage_number} (${stage.name}): Started`);
          } else if (stage.status === 'completed') {
            addLog('success', `✅ Stage ${stage.stage_number} (${stage.name}): Completed`);
          } else if (stage.status === 'failed') {
            addLog('error', `❌ Stage ${stage.stage_number} (${stage.name}): Failed - ${stage.error_message || 'Unknown error'}`);
          }
        }
      });
    }

    previousStatusRef.current = workflowStatus;
  }, [workflowStatus]);

  // Fetch detailed task logs periodically
  useEffect(() => {
    if (!flowRunId) {
      console.log('[WorkflowTerminal] No flowRunId, skipping log fetch');
      return;
    }

    const fetchDetailedLogs = async () => {
      try {
        console.log('[WorkflowTerminal] Fetching logs for flowRunId:', flowRunId);
        const response = await workflowAPI.getLogs(flowRunId, maxLines);
        console.log('[WorkflowTerminal] Logs response:', response);

        if (response && response.logs && response.logs.length > 0) {
          // Convert Prefect logs to terminal format
          const formattedLogs = response.logs.map(log => ({
            type: getLogType(log.level),
            message: `[${log.task_name}] ${log.message}`,
            timestamp: new Date(log.timestamp).toLocaleTimeString(),
            id: log.task_id + log.timestamp
          }));
          console.log('[WorkflowTerminal] Formatted logs:', formattedLogs.length, 'entries');
          setDetailedLogs(formattedLogs);
        } else {
          console.log('[WorkflowTerminal] No logs in response or empty logs array');
          // Set empty array instead of keeping old logs
          setDetailedLogs([]);
        }
      } catch (error) {
        console.error('[WorkflowTerminal] Failed to fetch detailed logs:', error);
        addLog('error', `❌ Failed to fetch detailed logs: ${error.message}`);
      }
    };

    // Initial fetch
    fetchDetailedLogs();

    // Poll every 3 seconds for new logs
    logsIntervalRef.current = setInterval(fetchDetailedLogs, 3000);

    return () => {
      if (logsIntervalRef.current) {
        clearInterval(logsIntervalRef.current);
      }
    };
  }, [flowRunId, maxLines]);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScrollRef.current && terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [logs, detailedLogs]);

  const addLog = (type, message) => {
    const timestamp = new Date().toLocaleTimeString();
    setLogs(prev => {
      const newLogs = [...prev, { type, message, timestamp, id: Date.now() + Math.random() }];
      // Keep only the last maxLines entries
      return newLogs.slice(-maxLines);
    });
  };

  const handleScroll = () => {
    if (!terminalRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = terminalRef.current;
    // Check if user is near the bottom (within 50px)
    autoScrollRef.current = scrollHeight - scrollTop - clientHeight < 50;
  };

  const clearLogs = () => {
    setLogs([]);
    addLog('info', '🧹 Terminal cleared');
  };

  const getLogType = (level) => {
    // Prefect uses numeric log levels: 10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR, 50=CRITICAL
    if (typeof level === 'number') {
      if (level >= 40) return 'error';   // ERROR or CRITICAL
      if (level >= 30) return 'warning'; // WARNING
      return 'info';                     // INFO or DEBUG
    }

    // Handle string levels as fallback
    const levelUpper = (level || 'INFO').toString().toUpperCase();
    if (levelUpper.includes('ERROR') || levelUpper.includes('CRITICAL')) return 'error';
    if (levelUpper.includes('WARNING') || levelUpper.includes('WARN')) return 'warning';
    if (levelUpper.includes('SUCCESS')) return 'success';
    return 'info';
  };

  const getLogClassName = (type) => {
    const baseClass = 'terminal-line';
    switch (type) {
      case 'error': return `${baseClass} terminal-error`;
      case 'success': return `${baseClass} terminal-success`;
      case 'warning': return `${baseClass} terminal-warning`;
      case 'info': return `${baseClass} terminal-info`;
      case 'status': return `${baseClass} terminal-status`;
      case 'progress': return `${baseClass} terminal-progress`;
      case 'stage': return `${baseClass} terminal-stage`;
      default: return baseClass;
    }
  };

  // Merge and sort all logs (status logs + detailed task logs)
  const allLogs = [...logs, ...detailedLogs]
    .sort((a, b) => {
      // Sort by timestamp (newest at bottom)
      const timeA = a.timestamp || '';
      const timeB = b.timestamp || '';
      return timeA.localeCompare(timeB);
    })
    .slice(-maxLines); // Keep only the last maxLines

  return (
    <div className="workflow-terminal">
      <div className="terminal-header">
        <div className="terminal-title">
          📟 Workflow Log Stream
          {workflowStatus && <span className="terminal-status connected">● Active</span>}
          {!workflowStatus && <span className="terminal-status disconnected">○ Waiting</span>}
        </div>
        <div className="terminal-controls">
          <button
            className="terminal-btn"
            onClick={clearLogs}
            title="Clear terminal"
          >
            🧹 Clear
          </button>
          <button
            className="terminal-btn"
            onClick={() => { autoScrollRef.current = !autoScrollRef.current; }}
            title={autoScrollRef.current ? "Disable auto-scroll" : "Enable auto-scroll"}
          >
            {autoScrollRef.current ? '📌 Auto' : '📌 Manual'}
          </button>
        </div>
      </div>
      <div
        ref={terminalRef}
        className="terminal-content"
        style={{ height: `${height}px` }}
        onScroll={handleScroll}
      >
        {allLogs.length === 0 && (
          <div className="terminal-line terminal-info">
            ⏳ Waiting for workflow updates...
          </div>
        )}
        {allLogs.map(log => (
          <div key={log.id} className={getLogClassName(log.type)}>
            <span className="terminal-timestamp">[{log.timestamp}]</span>
            <span className="terminal-message">{log.message}</span>
          </div>
        ))}
        {allLogs.length > 0 && detailedLogs.length === 0 && workflowStatus?.status === 'running' && (
          <div className="terminal-line terminal-info" style={{ marginTop: '16px', fontStyle: 'italic' }}>
            💡 Detailed task logs will appear here once translation starts...
          </div>
        )}
      </div>
    </div>
  );
}

export default WorkflowTerminal;
