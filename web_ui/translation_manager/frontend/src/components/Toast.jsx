import React, { useState, useEffect } from 'react';
import './Toast.css';

/**
 * Toast Notification Component
 *
 * Non-blocking notifications that appear at the top-right of the screen
 * and auto-dismiss after a few seconds.
 *
 * Features:
 * - Debouncing: Prevent duplicate messages within 5 seconds
 * - Queue management: Max 3 visible toasts at once
 * - Auto-dismiss with configurable duration
 */

let toastId = 0;
const toastListeners = [];
const recentMessages = new Map(); // Track recent messages for debouncing
const MAX_VISIBLE_TOASTS = 3;

// Debounce duplicate messages
const isDuplicate = (message, type) => {
  const key = `${type}:${message}`;
  const lastShown = recentMessages.get(key);
  const now = Date.now();

  if (lastShown && (now - lastShown) < 5000) {
    // Same message shown within last 5 seconds - skip it
    return true;
  }

  recentMessages.set(key, now);

  // Clean up old entries (older than 10 seconds)
  for (const [k, timestamp] of recentMessages.entries()) {
    if (now - timestamp > 10000) {
      recentMessages.delete(k);
    }
  }

  return false;
};

export const showToast = (message, type = 'info', duration = 4000) => {
  // Skip duplicate messages
  if (isDuplicate(message, type)) {
    return;
  }

  const toast = {
    id: toastId++,
    message,
    type, // 'success', 'error', 'warning', 'info'
    duration,
    timestamp: Date.now()
  };

  toastListeners.forEach(listener => listener(toast));
};

export const ToastContainer = () => {
  const [toasts, setToasts] = useState([]);
  const [queue, setQueue] = useState([]);

  useEffect(() => {
    const addToast = (toast) => {
      setToasts(prev => {
        // If we're at max capacity, queue it
        if (prev.length >= MAX_VISIBLE_TOASTS) {
          setQueue(q => [...q, toast]);
          return prev;
        }

        // Add to visible toasts
        const newToasts = [...prev, toast];

        // Auto-remove after duration
        setTimeout(() => {
          setToasts(current => {
            const updated = current.filter(t => t.id !== toast.id);

            // If we removed a toast and have queued toasts, show the next one
            setQueue(q => {
              if (q.length > 0) {
                const [next, ...rest] = q;
                // Add the next queued toast
                setTimeout(() => addToast(next), 100);
                return rest;
              }
              return q;
            });

            return updated;
          });
        }, toast.duration);

        return newToasts;
      });
    };

    toastListeners.push(addToast);

    return () => {
      const index = toastListeners.indexOf(addToast);
      if (index > -1) {
        toastListeners.splice(index, 1);
      }
    };
  }, []);

  const removeToast = (id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  };

  return (
    <div className="toast-container">
      {toasts.map(toast => (
        <div
          key={toast.id}
          className={`toast toast-${toast.type}`}
          onClick={() => removeToast(toast.id)}
        >
          <div className="toast-icon">
            {toast.type === 'success' && '✓'}
            {toast.type === 'error' && '✕'}
            {toast.type === 'warning' && '⚠'}
            {toast.type === 'info' && 'ℹ'}
          </div>
          <div className="toast-message">{toast.message}</div>
          <button
            className="toast-close"
            onClick={(e) => {
              e.stopPropagation();
              removeToast(toast.id);
            }}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
};

export default ToastContainer;
