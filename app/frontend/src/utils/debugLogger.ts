/**
 * Remote debug logger — ships frontend logs to the backend for persistence in Lakebase.
 *
 * Disabled by default. Call `debugLogger.enable()` when `/api/ready` returns
 * `debug_client_logs: true`. When disabled, `debugLog()` just delegates to
 * `console.*` with zero overhead.
 */

interface LogEntry {
  level: string;
  source: string;
  message: string;
  metadata?: Record<string, unknown>;
  timestamp: string;
  sessionId: string;
}

const FLUSH_INTERVAL_MS = 3000;
const FLUSH_THRESHOLD = 20;

let enabled = false;
let sessionId = '';
let queue: LogEntry[] = [];
let flushTimer: ReturnType<typeof setInterval> | null = null;

function generateSessionId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function flush() {
  if (queue.length === 0) return;
  const batch = queue.splice(0);
  fetch('/api/debug/client-logs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ entries: batch }),
  }).catch(() => {
    // Network failure — silently drop, don't re-queue to avoid infinite growth
  });
}

function enqueue(entry: LogEntry) {
  queue.push(entry);
  if (queue.length >= FLUSH_THRESHOLD) {
    flush();
  }
}

export function debugLog(
  level: 'error' | 'warn' | 'info' | 'debug',
  source: string,
  message: string,
  metadata?: Record<string, unknown>,
) {
  // Always log to console
  const consoleFn = level === 'error' ? console.error
    : level === 'warn' ? console.warn
    : level === 'debug' ? console.debug
    : console.log;
  const tag = `[${source}]`;
  if (metadata) {
    consoleFn(tag, message, metadata);
  } else {
    consoleFn(tag, message);
  }

  // Ship to backend when enabled
  if (enabled) {
    enqueue({
      level,
      source,
      message,
      metadata,
      timestamp: new Date().toISOString(),
      sessionId,
    });
  }
}

export const debugLogger = {
  enable() {
    if (enabled) return;
    enabled = true;
    sessionId = generateSessionId();
    flushTimer = setInterval(flush, FLUSH_INTERVAL_MS);
    debugLog('info', 'debugLogger', `enabled (session=${sessionId})`);
  },

  disable() {
    if (!enabled) return;
    flush(); // send anything remaining
    enabled = false;
    if (flushTimer) {
      clearInterval(flushTimer);
      flushTimer = null;
    }
  },

  get isEnabled() {
    return enabled;
  },
};
