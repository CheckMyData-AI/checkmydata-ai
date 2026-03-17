const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

function getAuthHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const token = localStorage.getItem("auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const { headers: optHeaders, ...restOptions } = options ?? {};
  const res = await fetch(`${API_BASE}${path}`, {
    ...restOptions,
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeaders(),
      ...(optHeaders instanceof Headers
        ? Object.fromEntries(optHeaders.entries())
        : Array.isArray(optHeaders)
          ? Object.fromEntries(optHeaders)
          : optHeaders),
    },
  });
  if (!res.ok) {
    const isAuthRoute = path.startsWith("/auth/");
    if (res.status === 401 && !isAuthRoute && typeof window !== "undefined") {
      try {
        const { useAuthStore } = await import("@/stores/auth-store");
        useAuthStore.getState().logout();
      } catch {
        localStorage.removeItem("auth_token");
        localStorage.removeItem("auth_user");
      }
      window.location.reload();
      throw new Error("Session expired. Please log in again.");
    }
    if (res.status === 429) {
      throw new Error("Too many requests. Please wait a moment and try again.");
    }
    const body = await res.json().catch(() => ({}));
    const detail = Array.isArray(body.detail)
      ? body.detail.map((e: { msg?: string; message?: string }) => e.msg ?? e.message ?? "Validation error").join("; ")
      : body.detail || `Request failed: ${res.status}`;
    throw new Error(detail);
  }
  return res.json();
}

export interface Project {
  id: string;
  name: string;
  description: string;
  repo_url: string | null;
  repo_branch: string;
  ssh_key_id: string | null;
  indexing_llm_provider: string | null;
  indexing_llm_model: string | null;
  agent_llm_provider: string | null;
  agent_llm_model: string | null;
  sql_llm_provider: string | null;
  sql_llm_model: string | null;
  owner_id: string | null;
  user_role: string | null;
}

export interface ProjectInvite {
  id: string;
  project_id: string;
  email: string;
  role: string;
  status: string;
  invited_by: string;
  created_at: string | null;
  accepted_at: string | null;
}

export interface ProjectMember {
  id: string;
  project_id: string;
  user_id: string;
  role: string;
  email: string | null;
  display_name: string | null;
}

export interface Connection {
  id: string;
  project_id: string;
  name: string;
  db_type: string;
  ssh_host: string | null;
  ssh_port: number;
  ssh_user: string | null;
  ssh_key_id: string | null;
  db_host: string;
  db_port: number;
  db_name: string;
  db_user: string | null;
  is_read_only: boolean;
  is_active: boolean;
  ssh_exec_mode: boolean;
  ssh_command_template: string | null;
  ssh_pre_commands: string | null;
}

export interface SshKey {
  id: string;
  name: string;
  fingerprint: string;
  key_type: string;
  created_at: string;
}

export interface ChatSession {
  id: string;
  project_id: string;
  title: string;
  connection_id?: string | null;
}

export interface ChatMessageDTO {
  id: string;
  role: string;
  content: string;
  metadata_json: string | null;
  tool_calls_json: string | null;
  user_rating: number | null;
  created_at: string;
}

export interface ChatResponse {
  session_id: string;
  answer: string;
  query: string | null;
  query_explanation: string | null;
  visualization: Record<string, unknown> | null;
  error: string | null;
  workflow_id: string | null;
  staleness_warning: string | null;
  response_type?: "text" | "sql_result" | "knowledge" | "error";
  assistant_message_id?: string | null;
  user_message_id?: string | null;
  raw_result?: { columns: string[]; rows: unknown[][]; total_rows: number } | null;
  rag_sources?: Array<{ source_path: string; distance?: number; doc_type?: string }> | null;
  token_usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number } | null;
}

export interface RepoCheckResult {
  accessible: boolean;
  branches: string[];
  default_branch: string | null;
  error: string | null;
}

export interface RepoStatus {
  project_id: string;
  repo_url: string;
  last_indexed_commit: string | null;
  last_indexed_at: string | null;
  branch: string;
  indexed_files_count: number;
  total_documents: number;
  is_indexing: boolean;
}

export interface UpdateCheck {
  has_updates: boolean;
  commits_behind: number;
  message: string;
}

export interface DbIndexStatus {
  is_indexed: boolean;
  is_indexing?: boolean;
  indexed_at?: string | null;
  total_tables?: number;
  active_tables?: number;
  empty_tables?: number;
  orphan_tables?: number;
  phantom_tables?: number;
}

export interface DbIndexResponse {
  tables: {
    table_name: string;
    table_schema: string;
    column_count: number;
    row_count: number | null;
    is_active: boolean;
    relevance_score: number;
    business_description: string;
    query_hints: string;
    code_match_status: string;
    indexed_at: string | null;
  }[];
  summary?: {
    total_tables: number;
    active_tables: number;
    empty_tables: number;
    orphan_tables: number;
    phantom_tables: number;
    summary_text: string;
    recommendations: string;
    indexed_at: string | null;
  } | null;
}

export interface LLMModel {
  id: string;
  name: string;
  context_length: number | null;
  pricing: { prompt: string; completion: string } | null;
}

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
}

export interface AuthResponse {
  token: string;
  user: AuthUser;
}

export const api = {
  auth: {
    register: (email: string, password: string, displayName?: string) =>
      request<AuthResponse>("/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password, display_name: displayName || "" }),
      }),
    login: (email: string, password: string) =>
      request<AuthResponse>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      }),
    googleLogin: (credential: string) =>
      request<AuthResponse>("/auth/google", {
        method: "POST",
        body: JSON.stringify({ credential }),
      }),
  },

  projects: {
    list: () => request<Project[]>("/projects"),
    get: (id: string) => request<Project>(`/projects/${id}`),
    create: (data: Partial<Project>) =>
      request<Project>("/projects", { method: "POST", body: JSON.stringify(data) }),
    update: (id: string, data: Partial<Project>) =>
      request<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<{ ok: boolean }>(`/projects/${id}`, { method: "DELETE" }),
  },

  connections: {
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
      request<{ success: boolean; hostname?: string; error?: string }>(`/connections/${id}/test-ssh`, {
        method: "POST",
      }),
    refreshSchema: (id: string) =>
      request<{ ok: boolean; tables: number; db_type: string }>(`/connections/${id}/refresh-schema`, {
        method: "POST",
      }),
    indexDb: (id: string) =>
      request<{ status: string; connection_id: string }>(`/connections/${id}/index-db`, {
        method: "POST",
      }),
    indexDbStatus: (id: string) =>
      request<DbIndexStatus>(`/connections/${id}/index-db/status`),
    getDbIndex: (id: string) =>
      request<DbIndexResponse>(`/connections/${id}/index-db`),
    deleteDbIndex: (id: string) =>
      request<{ ok: boolean }>(`/connections/${id}/index-db`, { method: "DELETE" }),
  },

  chat: {
    createSession: (projectId: string, title?: string) =>
      request<ChatSession>("/chat/sessions", {
        method: "POST",
        body: JSON.stringify({ project_id: projectId, title }),
      }),
    listSessions: (projectId: string) =>
      request<ChatSession[]>(`/chat/sessions/${projectId}`),
    updateSession: (sessionId: string, data: { title: string }) =>
      request<ChatSession>(`/chat/sessions/${sessionId}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    generateTitle: (sessionId: string) =>
      request<ChatSession>(`/chat/sessions/${sessionId}/generate-title`, {
        method: "POST",
      }),
    deleteSession: (sessionId: string) =>
      request<{ ok: boolean }>(`/chat/sessions/${sessionId}`, { method: "DELETE" }),
    submitFeedback: (messageId: string, rating: number) =>
      request<{ ok: boolean; message_id: string; rating: number }>("/chat/feedback", {
        method: "POST",
        body: JSON.stringify({ message_id: messageId, rating }),
      }),
    getFeedbackAnalytics: (projectId: string) =>
      request<{ total_rated: number; positive: number; negative: number }>(
        `/chat/analytics/feedback/${projectId}`,
      ),
    getMessages: (sessionId: string) =>
      request<ChatMessageDTO[]>(`/chat/sessions/${sessionId}/messages`),
    ask: (data: {
      project_id: string;
      connection_id?: string;
      message: string;
      session_id?: string;
      preferred_provider?: string;
      model?: string;
    }) =>
      request<ChatResponse>("/chat/ask", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    askStream: (
      data: {
        project_id: string;
        connection_id?: string;
        message: string;
        session_id?: string;
        preferred_provider?: string;
        model?: string;
      },
      onStep: (event: Record<string, unknown>) => void,
      onResult: (result: ChatResponse) => void,
      onError: (error: string) => void,
      onToolCall?: (event: Record<string, unknown>) => void,
    ) => {
      const ctrl = new AbortController();
      fetch(`${API_BASE}/chat/ask/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify(data),
        signal: ctrl.signal,
      }).then(async (res) => {
        if (res.status === 401) {
          onError("Session expired");
          window.location.reload();
          return;
        }
        if (!res.ok || !res.body) {
          onError(`Stream failed: ${res.status}`);
          return;
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop() || "";
          for (const part of parts) {
            const eventMatch = part.match(/^event:\s*(\w+)\ndata:\s*(.+)$/s);
            if (!eventMatch) continue;
            const [, eventType, jsonStr] = eventMatch;
            try {
              const parsed = JSON.parse(jsonStr);
              if (eventType === "step") onStep(parsed);
              else if (eventType === "tool_call") onToolCall?.(parsed);
              else if (eventType === "result") onResult(parsed as ChatResponse);
              else if (eventType === "error") onError(parsed.error);
            } catch { /* skip malformed */ }
          }
        }
      }).catch((err) => {
        if (err.name !== "AbortError") onError(String(err));
      });
      return ctrl;
    },
  },

  sshKeys: {
    list: () => request<SshKey[]>("/ssh-keys"),
    create: (data: { name: string; private_key: string; passphrase?: string }) =>
      request<SshKey>("/ssh-keys", { method: "POST", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<{ ok: boolean }>(`/ssh-keys/${id}`, { method: "DELETE" }),
  },

  repos: {
    checkAccess: (data: { repo_url: string; ssh_key_id?: string | null }) =>
      request<RepoCheckResult>("/repos/check-access", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    index: (projectId: string, forceFull = false) =>
      request<{ status: string; workflow_id: string | null; resumed?: boolean; commit_sha?: string; files_indexed?: number; schemas_found?: number }>(
        `/repos/${projectId}/index`,
        { method: "POST", body: JSON.stringify({ force_full: forceFull }) }
      ),
    docs: (projectId: string) =>
      request<{ id: string; doc_type: string; source_path: string; commit_sha: string | null; updated_at: string | null }[]>(
        `/repos/${projectId}/docs`,
      ),
    doc: (projectId: string, docId: string) =>
      request<{ id: string; doc_type: string; source_path: string; content: string }>(
        `/repos/${projectId}/docs/${docId}`,
      ),
    status: (projectId: string) =>
      request<RepoStatus>(`/repos/${projectId}/status`),
    checkUpdates: (projectId: string) =>
      request<UpdateCheck>(`/repos/${projectId}/check-updates`, { method: "POST" }),
  },

  rules: {
    list: (projectId?: string) =>
      request<{ id: string; project_id: string | null; name: string; content: string; format: string; is_default: boolean }[]>(
        `/rules${projectId ? `?project_id=${projectId}` : ""}`,
      ),
    create: (data: { project_id?: string; name: string; content: string; format?: string }) =>
      request<{ id: string; project_id: string | null; name: string; content: string; format: string; is_default: boolean }>(
        "/rules",
        { method: "POST", body: JSON.stringify(data) },
      ),
    update: (id: string, data: Record<string, unknown>) =>
      request<{ id: string; project_id: string | null; name: string; content: string; format: string; is_default: boolean }>(
        `/rules/${id}`,
        { method: "PATCH", body: JSON.stringify(data) },
      ),
    delete: (id: string) =>
      request<{ ok: boolean }>(`/rules/${id}`, { method: "DELETE" }),
  },

  invites: {
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
    listPending: () =>
      request<ProjectInvite[]>("/invites/pending"),
    accept: (inviteId: string) =>
      request<{ ok: boolean; project_id: string; role: string }>(
        `/invites/accept/${inviteId}`,
        { method: "POST" },
      ),
    listMembers: (projectId: string) =>
      request<ProjectMember[]>(`/invites/${projectId}/members`),
    removeMember: (projectId: string, userId: string) =>
      request<{ ok: boolean }>(`/invites/${projectId}/members/${userId}`, {
        method: "DELETE",
      }),
  },

  models: {
    list: (provider: string) =>
      request<LLMModel[]>(`/models?provider=${encodeURIComponent(provider)}`),
  },

  viz: {
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
        try {
          const { useAuthStore } = await import("@/stores/auth-store");
          useAuthStore.getState().logout();
        } catch {
          localStorage.removeItem("auth_token");
          localStorage.removeItem("auth_user");
        }
        window.location.reload();
        throw new Error("Session expired. Please log in again.");
      }
      if (!res.ok) throw new Error("Export failed");
      return res.blob();
    },
  },
};
