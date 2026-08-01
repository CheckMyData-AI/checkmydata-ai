import { request } from "./_client";
import type {
  AgentLearningDTO,
  Connection,
  ConnectionHealthState,
  DbIndexResponse,
  DbIndexStatus,
  LearningsStatus,
  SyncResponse,
  SyncStatus,
} from "./types";

/**
 * Overall collection outcome (spec §2.4 + `ConnectionService.collection_status`).
 * `never_collected` is its own state on purpose — it is not a kind of failure.
 */
export type CollectionOutcome = "ok" | "partial" | "failed" | "never_collected";

export interface CollectionReportStatus {
  report: string;
  grain?: string | null;
  /** Newest period with rows. Null while every collected period was empty. */
  latest_ok_period: string | null;
  /** Newest period the journal completed at all (`ok` **or** `empty`). */
  latest_collected_period?: string | null;
  ok_periods: number;
  empty_periods: number;
  failed_periods: number;
  rows_written: number;
  /** How many expected periods the journal has not completed. */
  pending_periods: number;
  /** The first few pending periods, for display. */
  pending_sample?: string[] | null;
  last_run_at?: string | null;
  /** Set only by a genuinely `failed` journal row. */
  last_error?: string | null;
  /**
   * Partial-data note carried by a **non-failed** row — a truncated vendor page
   * or a sampled range. A caveat qualifies data that did arrive; it is never an
   * error, and the two fields are deliberately separate on the wire.
   */
  caveat?: string | null;
}

export interface CollectionStatus {
  connection_id?: string;
  source_type?: string;
  collection_enabled?: boolean;
  collection_hour?: number;
  /** Hour-of-day (0–23) the schedule next fires; null when auto-collect is off. */
  next_scheduled_hour: number | null;
  /** IANA zone the collection hour is expressed in. */
  timezone?: string;
  backfill_days?: number;
  status: CollectionOutcome;
  last_run_at: string | null;
  last_error?: string | null;
  caveat?: string | null;
  /** Total pending periods across every report. */
  pending_periods: number;
  reports: CollectionReportStatus[];
}

export interface CollectNowResponse {
  status: string;
  task_id?: string;
  connection_id?: string;
}

export const connections = {
  listByProject: (projectId: string) =>
    request<Connection[]>(`/connections/project/${projectId}`),
  get: (id: string) => request<Connection>(`/connections/${id}`),
  create: (data: Record<string, unknown>) =>
    request<Connection>("/connections", { method: "POST", body: JSON.stringify(data) }),
  update: (id: string, data: Record<string, unknown>) =>
    request<Connection>(`/connections/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  delete: (id: string) =>
    request<{ ok: boolean }>(`/connections/${id}`, { method: "DELETE" }),
  test: (id: string) =>
    request<{ success: boolean; error?: string }>(`/connections/${id}/test`, {
      method: "POST",
    }),
  testSsh: (id: string) =>
    request<{ success: boolean; hostname?: string; error?: string }>(
      `/connections/${id}/test-ssh`,
      { method: "POST" },
    ),
  refreshSchema: (id: string) =>
    request<{ ok: boolean; tables: number; db_type: string }>(
      `/connections/${id}/refresh-schema`,
      { method: "POST" },
    ),
  indexDb: (id: string) =>
    request<{ status: string; run_id: string; workflow_id: string; connection_id: string }>(
      `/connections/${id}/index-db`,
      { method: "POST" },
    ),
  indexDbStatus: (id: string) =>
    request<DbIndexStatus>(`/connections/${id}/index-db/status`),
  getDbIndex: (id: string) => request<DbIndexResponse>(`/connections/${id}/index-db`),
  deleteDbIndex: (id: string) =>
    request<{ ok: boolean }>(`/connections/${id}/index-db`, { method: "DELETE" }),

  triggerSync: (id: string) =>
    request<{ status: string; run_id: string; workflow_id: string; connection_id: string }>(
      `/connections/${id}/sync`,
      { method: "POST" },
    ),
  syncStatus: (id: string) => request<SyncStatus>(`/connections/${id}/sync/status`),
  getSync: (id: string) => request<SyncResponse>(`/connections/${id}/sync`),
  deleteSync: (id: string) =>
    request<{ ok: boolean }>(`/connections/${id}/sync`, { method: "DELETE" }),

  /** Journal summary for an analytics source (spec §5). */
  collectionStatus: (id: string) =>
    request<CollectionStatus>(`/connections/${id}/collection-status`),
  /** Manual "collect now" — enqueues the same job the hourly cron dispatches. */
  collectNow: (id: string) =>
    request<CollectNowResponse>(`/connections/${id}/collect`, { method: "POST" }),

  learningsStatus: (id: string) =>
    request<LearningsStatus>(`/connections/${id}/learnings/status`),
  listLearnings: (id: string) =>
    request<AgentLearningDTO[]>(`/connections/${id}/learnings`),
  learningsSummary: (id: string) =>
    request<{ compiled_prompt: string }>(`/connections/${id}/learnings/summary`),
  updateLearning: (
    connId: string,
    learningId: string,
    data: { lesson?: string; is_active?: boolean; confidence?: number },
  ) =>
    request<{ ok: boolean; id: string }>(
      `/connections/${connId}/learnings/${learningId}`,
      { method: "PATCH", body: JSON.stringify(data) },
    ),
  deleteLearning: (connId: string, learningId: string) =>
    request<{ ok: boolean }>(`/connections/${connId}/learnings/${learningId}`, {
      method: "DELETE",
    }),
  clearLearnings: (connId: string) =>
    request<{ ok: boolean; deleted: number }>(`/connections/${connId}/learnings`, {
      method: "DELETE",
    }),
  recompileLearnings: (connId: string) =>
    request<{ ok: boolean; compiled_prompt: string }>(
      `/connections/${connId}/learnings/recompile`,
      { method: "POST" },
    ),
  confirmLearning: (connId: string, learningId: string) =>
    request<{
      ok: boolean;
      id: string;
      confidence: number;
      times_confirmed: number;
    }>(`/connections/${connId}/learnings/${learningId}/confirm`, { method: "POST" }),
  contradictLearning: (connId: string, learningId: string) =>
    request<{ ok: boolean; id: string; confidence: number; is_active: boolean }>(
      `/connections/${connId}/learnings/${learningId}/contradict`,
      { method: "POST" },
    ),
  health: (id: string) =>
    request<ConnectionHealthState>(`/connections/${id}/health`),
  healthAll: (projectId: string) =>
    request<Record<string, ConnectionHealthState>>(
      `/connections/health?project_id=${projectId}`,
    ),
  reconnect: (id: string) =>
    request<{ success: boolean; health?: ConnectionHealthState; error?: string }>(
      `/connections/${id}/reconnect`,
      { method: "POST" },
    ),
};
