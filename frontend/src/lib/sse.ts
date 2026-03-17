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
  return localStorage.getItem("auth_token");
}

function parseSSEChunk(buffer: string, onEvent: WorkflowEventHandler): string {
  const parts = buffer.split("\n\n");
  const remaining = parts.pop() || "";
  for (const part of parts) {
    const eventMatch = part.match(/^event:\s*(\w+)\ndata:\s*(.+)$/s);
    if (!eventMatch) continue;
    const [, , jsonStr] = eventMatch;
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
): () => void {
  const ctrl = new AbortController();
  const token = getToken();

  fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal: ctrl.signal,
  })
    .then(async (res) => {
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
): () => void {
  const url = `${API_BASE}/workflows/events?workflow_id=${encodeURIComponent(workflowId)}`;
  return createSSEStream(url, onEvent, onError);
}

export function subscribeToAllEvents(
  onEvent: WorkflowEventHandler,
  onError?: (err: unknown) => void,
): () => void {
  const url = `${API_BASE}/workflows/events`;
  return createSSEStream(url, onEvent, onError);
}
