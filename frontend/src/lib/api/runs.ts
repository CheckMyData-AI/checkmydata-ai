import { request } from "./_client";
import type { RunHistoryItem } from "./types";

export interface RunEvent {
  ts: string | null;
  step: string;
  status: string;
  detail: string;
  elapsed_ms: number | null;
  progress_pct: number | null;
  level: string;
}

export const runs = {
  cancel: (runId: string) =>
    request<{ cancelled: boolean; run_id: string }>(`/runs/${runId}/cancel`, {
      method: "POST",
    }),
  retry: (runId: string, forceFull = false) =>
    request<{ run_id: string; workflow_id: string; status: string }>(`/runs/${runId}/retry`, {
      method: "POST",
      body: JSON.stringify({ force_full: forceFull }),
    }),
  get: (runId: string) => request<RunHistoryItem>(`/runs/${runId}`),
  events: (runId: string, level?: string) =>
    request<RunEvent[]>(`/runs/${runId}/events${level ? `?level=${level}` : ""}`),
};
