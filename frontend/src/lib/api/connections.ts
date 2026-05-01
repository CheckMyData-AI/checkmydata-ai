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
    request<{ status: string; connection_id: string }>(
      `/connections/${id}/index-db`,
      { method: "POST" },
    ),
  indexDbStatus: (id: string) =>
    request<DbIndexStatus>(`/connections/${id}/index-db/status`),
  getDbIndex: (id: string) => request<DbIndexResponse>(`/connections/${id}/index-db`),
  deleteDbIndex: (id: string) =>
    request<{ ok: boolean }>(`/connections/${id}/index-db`, { method: "DELETE" }),

  triggerSync: (id: string) =>
    request<{ status: string; connection_id: string }>(`/connections/${id}/sync`, {
      method: "POST",
    }),
  syncStatus: (id: string) => request<SyncStatus>(`/connections/${id}/sync/status`),
  getSync: (id: string) => request<SyncResponse>(`/connections/${id}/sync`),
  deleteSync: (id: string) =>
    request<{ ok: boolean }>(`/connections/${id}/sync`, { method: "DELETE" }),

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
