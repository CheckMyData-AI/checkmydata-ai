import { handleSessionExpired } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

export interface WorkflowEvent {
  workflow_id: string;
  step: string;
  status: "started" | "completed" | "failed" | "skipped";
  detail: string;
  elapsed_ms: number | null;
  timestamp: number;
  pipeline: string;
  extra: Record<string, unknown>;
}

export type WorkflowEventHandler = (event: WorkflowEvent) => void;

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem("auth_token");
  } catch {
    return null;
  }
}

function parseSSEChunk(buffer: string, onEvent: WorkflowEventHandler): string {
  const parts = buffer.split("\n\n");
  const remaining = parts.pop() || "";
  for (const part of parts) {
    let eventType = "";
    const dataLines: string[] = [];
    for (const line of part.split("\n")) {
      if (line.startsWith("event:")) {
        eventType = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
      // ignore id:, retry:, and comments (lines starting with :)
    }
    if (dataLines.length === 0) continue;
    const jsonStr = dataLines.join("\n");
    try {
      onEvent(JSON.parse(jsonStr) as WorkflowEvent);
    } catch {
      /* skip malformed */
    }
  }
  return remaining;
}

function createSSEStream(
  url: string,
  onEvent: WorkflowEventHandler,
  onError?: (err: unknown) => void,
  onEnd?: () => void,
): () => void {
  const ctrl = new AbortController();
  const token = getToken();

  fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal: ctrl.signal,
  })
    .then(async (res) => {
      if (res.status === 401 && typeof window !== "undefined") {
        handleSessionExpired();
        onError?.(new Error("Session expired"));
        return;
      }
      if (!res.ok || !res.body) {
        onError?.(new Error(`SSE stream failed: ${res.status}`));
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        buffer = parseSSEChunk(buffer, onEvent);
      }
      onEnd?.();
    })
    .catch((err) => {
      if (err?.name !== "AbortError") onError?.(err);
    });

  return () => ctrl.abort();
}

export function subscribeToWorkflow(
  workflowId: string,
  onEvent: WorkflowEventHandler,
  onError?: (err: unknown) => void,
  onEnd?: () => void,
): () => void {
  const url = `${API_BASE}/workflows/events?workflow_id=${encodeURIComponent(workflowId)}`;
  return createSSEStream(url, onEvent, onError, onEnd);
}

export function subscribeToAllEvents(
  onEvent: WorkflowEventHandler,
  onError?: (err: unknown) => void,
  onEnd?: () => void,
): () => void {
  const url = `${API_BASE}/workflows/events`;
  return createSSEStream(url, onEvent, onError, onEnd);
}

const _listeners = new Set<WorkflowEventHandler>();

/** Broadcast an event to all local listeners (no new SSE stream). */
export function broadcastEvent(event: WorkflowEvent): void {
  for (const fn of _listeners) {
    try { fn(event); } catch { /* listener error */ }
  }
}

/** Subscribe to locally-broadcast events. Returns unsubscribe function. */
export function onEvent(handler: WorkflowEventHandler): () => void {
  _listeners.add(handler);
  return () => { _listeners.delete(handler); };
}
