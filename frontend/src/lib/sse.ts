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

export function subscribeToWorkflow(
  workflowId: string,
  onEvent: WorkflowEventHandler,
  onError?: (err: Event) => void,
): () => void {
  const url = `${API_BASE}/workflows/events?workflow_id=${encodeURIComponent(workflowId)}`;
  const source = new EventSource(url);

  source.addEventListener("step", (e: MessageEvent) => {
    try {
      const parsed: WorkflowEvent = JSON.parse(e.data);
      onEvent(parsed);
    } catch {
      // ignore parse errors
    }
  });

  source.onerror = (e) => {
    onError?.(e);
  };

  return () => {
    source.close();
  };
}
