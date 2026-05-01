import { API_BASE, getAuthHeaders, handleSessionExpired, request } from "./_client";
import type {
  AppNotification,
  BatchQueryDTO,
  Dashboard,
  ExecuteNoteResponse,
  LLMModel,
  ProjectInvite,
  ProjectMember,
  RepoCheckResult,
  RepoStatus,
  SavedNote,
  ScheduledQuery,
  ScheduleRun,
  SshKey,
  UpdateCheck,
  UsageStatsResponse,
} from "./types";

export const sshKeys = {
  list: () => request<SshKey[]>("/ssh-keys"),
  create: (data: { name: string; private_key: string; passphrase?: string }) =>
    request<SshKey>("/ssh-keys", { method: "POST", body: JSON.stringify(data) }),
  delete: (id: string) => request<{ ok: boolean }>(`/ssh-keys/${id}`, { method: "DELETE" }),
};

export const repos = {
  checkAccess: (data: { repo_url: string; ssh_key_id?: string | null }) =>
    request<RepoCheckResult>("/repos/check-access", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  index: (projectId: string, forceFull = false) =>
    request<{
      status: string;
      workflow_id: string | null;
      resumed?: boolean;
      commit_sha?: string;
      files_indexed?: number;
      schemas_found?: number;
    }>(`/repos/${projectId}/index`, {
      method: "POST",
      body: JSON.stringify({ force_full: forceFull }),
    }),
  docs: (projectId: string) =>
    request<
      {
        id: string;
        doc_type: string;
        source_path: string;
        commit_sha: string | null;
        updated_at: string | null;
      }[]
    >(`/repos/${projectId}/docs`),
  doc: (projectId: string, docId: string) =>
    request<{ id: string; doc_type: string; source_path: string; content: string }>(
      `/repos/${projectId}/docs/${docId}`,
    ),
  status: (projectId: string) => request<RepoStatus>(`/repos/${projectId}/status`),
  checkUpdates: (projectId: string) =>
    request<UpdateCheck>(`/repos/${projectId}/check-updates`, { method: "POST" }),
};

type Rule = {
  id: string;
  project_id: string | null;
  name: string;
  content: string;
  format: string;
  is_default: boolean;
};

export const rules = {
  list: (projectId?: string) =>
    request<Rule[]>(`/rules${projectId ? `?project_id=${projectId}` : ""}`),
  create: (data: { project_id?: string; name: string; content: string; format?: string }) =>
    request<Rule>("/rules", { method: "POST", body: JSON.stringify(data) }),
  update: (id: string, data: Record<string, unknown>) =>
    request<Rule>(`/rules/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  delete: (id: string) => request<{ ok: boolean }>(`/rules/${id}`, { method: "DELETE" }),
};

export const invites = {
  create: (projectId: string, email: string, role: string = "editor") =>
    request<ProjectInvite>(`/invites/${projectId}/invites`, {
      method: "POST",
      body: JSON.stringify({ email, role }),
    }),
  list: (projectId: string) =>
    request<ProjectInvite[]>(`/invites/${projectId}/invites`),
  revoke: (projectId: string, inviteId: string) =>
    request<{ ok: boolean }>(`/invites/${projectId}/invites/${inviteId}`, {
      method: "DELETE",
    }),
  resend: (projectId: string, inviteId: string) =>
    request<{ ok: boolean }>(`/invites/${projectId}/invites/${inviteId}/resend`, {
      method: "POST",
    }),
  listPending: () => request<ProjectInvite[]>("/invites/pending"),
  accept: (inviteId: string) =>
    request<{ ok: boolean; project_id: string; role: string }>(
      `/invites/accept/${inviteId}`,
      { method: "POST" },
    ),
  listMembers: (projectId: string) =>
    request<ProjectMember[]>(`/invites/${projectId}/members`),
  updateMemberRole: (projectId: string, userId: string, role: string) =>
    request<ProjectMember>(`/invites/${projectId}/members/${userId}`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    }),
  removeMember: (projectId: string, userId: string) =>
    request<{ ok: boolean }>(`/invites/${projectId}/members/${userId}`, {
      method: "DELETE",
    }),
};

export const notes = {
  list: (projectId: string, scope: "mine" | "shared" | "all" = "mine") =>
    request<SavedNote[]>(`/notes?project_id=${projectId}&scope=${scope}`),
  get: (id: string) => request<SavedNote>(`/notes/${id}`),
  create: (data: {
    project_id: string;
    connection_id?: string | null;
    title: string;
    comment?: string | null;
    sql_query: string;
    answer_text?: string | null;
    visualization_json?: string | null;
    last_result_json?: string | null;
  }) => request<SavedNote>("/notes", { method: "POST", body: JSON.stringify(data) }),
  update: (
    id: string,
    data: { title?: string; comment?: string | null; is_shared?: boolean },
  ) =>
    request<SavedNote>(`/notes/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  delete: (id: string) => request<{ ok: boolean }>(`/notes/${id}`, { method: "DELETE" }),
  execute: (id: string) =>
    request<ExecuteNoteResponse>(`/notes/${id}/execute`, {
      method: "POST",
      timeoutMs: 120_000,
    }),
};

export const dashboards = {
  list: (projectId: string) =>
    request<Dashboard[]>(`/dashboards?project_id=${projectId}`),
  get: (id: string) => request<Dashboard>(`/dashboards/${id}`),
  create: (data: {
    project_id: string;
    title: string;
    layout_json?: string | null;
    cards_json?: string | null;
    is_shared?: boolean;
  }) =>
    request<Dashboard>("/dashboards", { method: "POST", body: JSON.stringify(data) }),
  update: (
    id: string,
    data: {
      title?: string;
      layout_json?: string | null;
      cards_json?: string | null;
      is_shared?: boolean;
    },
  ) => request<Dashboard>(`/dashboards/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  delete: (id: string) => request<{ ok: boolean }>(`/dashboards/${id}`, { method: "DELETE" }),
};

export const models = {
  list: (provider: string) =>
    request<LLMModel[]>(`/models?provider=${encodeURIComponent(provider)}`),
};

export const viz = {
  render: (
    columns: string[],
    rows: unknown[][],
    vizType: string,
    config?: Record<string, unknown>,
  ) =>
    request<Record<string, unknown>>("/visualizations/render", {
      method: "POST",
      body: JSON.stringify({
        columns,
        rows,
        viz_type: vizType,
        config: config || {},
      }),
    }),
  export: async (columns: string[], rows: unknown[][], format: string) => {
    const res = await fetch(`${API_BASE}/visualizations/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify({ columns, rows, format }),
    });
    if (res.status === 401 && typeof window !== "undefined") {
      handleSessionExpired();
      throw new Error("Session expired. Please log in again.");
    }
    if (!res.ok) throw new Error("Export failed");
    return res.blob();
  },
};

export const tasks = {
  getActive: () =>
    request<
      {
        workflow_id: string;
        pipeline: string;
        started_at: number;
        extra: Record<string, unknown>;
      }[]
    >("/tasks/active"),
};

export const demo = {
  setup: () =>
    request<{ project_id: string; connection_id: string }>("/demo/setup", {
      method: "POST",
    }),
};

export const notifications = {
  list: (unreadOnly = true) =>
    request<AppNotification[]>(`/notifications?unread_only=${unreadOnly}`),
  count: () => request<{ count: number }>("/notifications/count"),
  markRead: (id: string) =>
    request<{ ok: boolean }>(`/notifications/${id}/read`, { method: "PATCH" }),
  markAllRead: () =>
    request<{ ok: boolean }>("/notifications/read-all", { method: "POST" }),
};

export const usage = {
  getStats: (days: number = 30) =>
    request<UsageStatsResponse>(`/usage/stats?days=${days}`),
};

export const schedules = {
  list: (projectId: string) =>
    request<ScheduledQuery[]>(`/schedules?project_id=${projectId}`),
  get: (id: string) => request<ScheduledQuery>(`/schedules/${id}`),
  create: (data: {
    project_id: string;
    connection_id: string;
    title: string;
    sql_query: string;
    cron_expression: string;
    alert_conditions?: string | null;
    notification_channels?: string | null;
  }) =>
    request<ScheduledQuery>("/schedules", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  update: (id: string, data: Record<string, unknown>) =>
    request<ScheduledQuery>(`/schedules/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  delete: (id: string) => request<{ ok: boolean }>(`/schedules/${id}`, { method: "DELETE" }),
  runNow: (id: string) =>
    request<ScheduleRun>(`/schedules/${id}/run-now`, {
      method: "POST",
      timeoutMs: 120_000,
    }),
  history: (id: string) => request<ScheduleRun[]>(`/schedules/${id}/history`),
};

export const batch = {
  execute: (data: {
    project_id: string;
    connection_id: string;
    title: string;
    queries: { sql: string; title: string }[];
    note_ids?: string[];
  }) =>
    request<{ batch_id: string; status: string }>("/batch/execute", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  get: (id: string) => request<BatchQueryDTO>(`/batch/${id}`),
  list: (projectId: string) =>
    request<BatchQueryDTO[]>(`/batch?project_id=${projectId}`),
  delete: (id: string) => request<{ ok: boolean }>(`/batch/${id}`, { method: "DELETE" }),
  export: async (id: string) => {
    const res = await fetch(`${API_BASE}/batch/${id}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    });
    if (res.status === 401 && typeof window !== "undefined") {
      handleSessionExpired();
      throw new Error("Session expired. Please log in again.");
    }
    if (!res.ok) throw new Error("Export failed");
    return res.blob();
  },
};
