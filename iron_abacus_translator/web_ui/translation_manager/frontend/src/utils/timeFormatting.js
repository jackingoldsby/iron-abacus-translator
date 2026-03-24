/**
 * Time Formatting Utilities
 *
 * Provides relative timestamps, duration formatting, and ETA calculations
 * for the Translation Management UI.
 */

/**
 * Format a timestamp as relative time (e.g., "2 hours ago", "just now")
 *
 * @param {string|Date} timestamp - ISO timestamp or Date object
 * @returns {string} Relative time string
 */
export function formatRelativeTime(timestamp) {
  if (!timestamp) return '-';

  const now = new Date();
  const then = new Date(timestamp);
  const diffMs = now - then;
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 10) return 'just now';
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  // Older than a week: show date
  return then.toLocaleDateString();
}

/**
 * Format a timestamp as a full readable string
 *
 * @param {string|Date} timestamp - ISO timestamp or Date object
 * @returns {string} Formatted timestamp
 */
export function formatFullTimestamp(timestamp) {
  if (!timestamp) return '-';

  const date = new Date(timestamp);
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true
  });
}

/**
 * Format duration in seconds to human-readable string
 *
 * @param {number} seconds - Duration in seconds
 * @returns {string} Formatted duration (e.g., "2h 15m", "45m", "30s")
 */
export function formatDuration(seconds) {
  if (!seconds || seconds < 0) return '-';

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  if (hours > 0) {
    return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  } else if (minutes > 0) {
    return secs > 0 ? `${minutes}m ${secs}s` : `${minutes}m`;
  } else {
    return `${secs}s`;
  }
}

/**
 * Calculate and format ETA (Estimated Time to Arrival)
 *
 * @param {number} progressPct - Progress percentage (0-100)
 * @param {number} elapsedSeconds - Elapsed time in seconds
 * @param {string} status - Current status (running, completed, etc.)
 * @returns {string} Formatted ETA or appropriate status message
 */
export function calculateETA(progressPct, elapsedSeconds, status = 'running') {
  // Don't show ETA for non-running workflows
  if (status !== 'running' && status !== 'pending') {
    return '-';
  }

  // Need some progress to calculate ETA
  if (!progressPct || progressPct < 1 || !elapsedSeconds || elapsedSeconds < 10) {
    return 'Calculating...';
  }

  // Calculate ETA based on current progress rate
  const remainingPct = 100 - progressPct;
  const secondsPerPct = elapsedSeconds / progressPct;
  const etaSeconds = remainingPct * secondsPerPct;

  // Format ETA
  return `~${formatDuration(etaSeconds)}`;
}

/**
 * Get color class for ETA based on remaining time
 *
 * @param {number} progressPct - Progress percentage
 * @param {number} elapsedSeconds - Elapsed time in seconds
 * @returns {string} CSS class name for color coding
 */
export function getETAColorClass(progressPct, elapsedSeconds) {
  if (!progressPct || progressPct < 1 || !elapsedSeconds) {
    return 'eta-unknown';
  }

  const remainingPct = 100 - progressPct;
  const secondsPerPct = elapsedSeconds / progressPct;
  const etaSeconds = remainingPct * secondsPerPct;
  const etaHours = etaSeconds / 3600;

  if (etaHours < 1) return 'eta-green';
  if (etaHours < 3) return 'eta-yellow';
  return 'eta-red';
}

/**
 * Format a compact timestamp for table displays
 * Shows relative time with abbreviated units
 *
 * @param {string|Date} timestamp - ISO timestamp or Date object
 * @returns {string} Compact relative time
 */
export function formatCompactRelativeTime(timestamp) {
  if (!timestamp) return '-';

  const now = new Date();
  const then = new Date(timestamp);
  const diffMs = now - then;
  const diffMins = Math.floor(diffMs / 1000 / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return 'now';
  if (diffMins < 60) return `${diffMins}m`;
  if (diffHours < 24) return `${diffHours}h`;
  if (diffDays < 7) return `${diffDays}d`;

  return then.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}
