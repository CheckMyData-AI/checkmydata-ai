import { request } from "./_client";
import type { AttentionResponse, SyncSchedule, KnowledgeHealth, PipelineStatusResponse, Project, ProjectReadiness, SyncHistoryResponse } from "./types";

export const projects = {
  list: () => request<Project[]>("/projects"),
  get: (id: string) => request<Project>(`/projects/${id}`),
  create: (data: Partial<Project>) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(data) }),
  update: (id: string, data: Partial<Project>) =>
    request<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  delete: (id: string) =>
    request<{ ok: boolean }>(`/projects/${id}`, { method: "DELETE" }),
  readiness: (id: string) => request<ProjectReadiness>(`/projects/${id}/readiness`),
  knowledgeHealth: (id: string, connectionId?: string | null) =>
    request<KnowledgeHealth>(
      `/projects/${id}/knowledge-health${
        connectionId ? `?connection_id=${encodeURIComponent(connectionId)}` : ""
      }`,
    ),
  pipelineStatus: (id: string) =>
    request<PipelineStatusResponse>(`/projects/${id}/pipeline-status`),
  syncHistory: (id: string, limit = 20) =>
    request<SyncHistoryResponse>(`/projects/${id}/sync-history?limit=${limit}`),
  attention: (id: string) => request<AttentionResponse>(`/projects/${id}/attention`),
  syncSchedule: (id: string) => request<SyncSchedule>(`/projects/${id}/sync-schedule`),
  setSyncSchedule: (id: string, data: { enabled?: boolean; hour?: number }) =>
    request<SyncSchedule>(`/projects/${id}/sync-schedule`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  requestAccess: (data: { email: string; description: string; message: string }) =>
    request<{ ok: boolean }>("/projects/access-requests", {
      method: "POST",
      body: JSON.stringify(data),
    }),
};
