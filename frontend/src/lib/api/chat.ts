import { API_BASE, getAuthHeaders, handleSessionExpired, request } from "./_client";
import type {
  ChatMessageDTO,
  ChatResponse,
  ChatSearchResult,
  ChatSession,
  CostEstimate,
  QuerySuggestion,
  StreamError,
} from "./types";

const STREAM_IDLE_TIMEOUT_MS = 120_000;
const PIPELINE_EVENTS = new Set([
  "plan",
  "plan_summary",
  "stage_start",
  "stage_result",
  "stage_validation",
  "stage_complete",
  "checkpoint",
  "stage_retry",
]);

export interface AskStreamInput {
  project_id: string;
  connection_id?: string;
  message: string;
  session_id?: string;
  preferred_provider?: string;
  model?: string;
  pipeline_action?: string;
  pipeline_run_id?: string;
  modification?: string;
  continuation_context?: string;
}

export type SessionRotatedEvent = {
  old_session_id: string;
  new_session_id: string;
  summary_preview: string;
  message_count: number;
  topics: string[];
};

export const chat = {
  listSessions: (projectId: string) =>
    request<ChatSession[]>(`/chat/sessions/${projectId}`),
  createSession: (data: { project_id: string; title?: string; connection_id?: string }) =>
    request<ChatSession>("/chat/sessions", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  ensureWelcome: (projectId: string, connectionId?: string) =>
    request<ChatSession & { created: boolean }>("/chat/sessions/ensure-welcome", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, connection_id: connectionId }),
    }),
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
  search: (projectId: string, query: string, limit?: number) =>
    request<ChatSearchResult[]>(
      `/chat/search?project_id=${projectId}&q=${encodeURIComponent(query)}&limit=${limit || 20}`,
    ),
  summarize: (messageId: string, projectId: string) =>
    request<{ summary: string; message_id: string }>("/chat/summarize", {
      method: "POST",
      body: JSON.stringify({ message_id: messageId, project_id: projectId }),
    }),
  explainSql: (sql: string, projectId: string, dbType?: string) =>
    request<{ explanation: string; complexity: string }>("/chat/explain-sql", {
      method: "POST",
      body: JSON.stringify({ sql, project_id: projectId, db_type: dbType }),
    }),
  suggestions: (projectId: string, connectionId: string, limit?: number) =>
    request<QuerySuggestion[]>(
      `/chat/suggestions?project_id=${projectId}&connection_id=${connectionId}&limit=${limit || 5}`,
    ),
  estimate: (projectId: string, connectionId?: string) =>
    request<CostEstimate>(
      `/chat/estimate?project_id=${projectId}${connectionId ? `&connection_id=${connectionId}` : ""}`,
    ),
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
    data: AskStreamInput,
    onStep: (event: Record<string, unknown>) => void,
    onResult: (result: ChatResponse) => void,
    onError: (error: StreamError) => void,
    onToolCall?: (event: Record<string, unknown>) => void,
    onPipelineEvent?: (eventType: string, event: Record<string, unknown>) => void,
    onThinking?: (event: Record<string, unknown>) => void,
    onToken?: (chunk: string) => void,
    onSessionRotated?: (event: SessionRotatedEvent) => void,
  ) => {
    const ctrl = new AbortController();
    let idleTimer: ReturnType<typeof setTimeout> | undefined;
    const resetIdleTimer = () => {
      if (idleTimer) clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        ctrl.abort("Stream idle timeout");
      }, STREAM_IDLE_TIMEOUT_MS);
    };
    resetIdleTimer();
    const streamPromise = fetch(`${API_BASE}/chat/ask/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify(data),
      signal: ctrl.signal,
    })
      .then(async (res) => {
        if (res.status === 401 && typeof window !== "undefined") {
          handleSessionExpired();
          onError({
            error: "Session expired",
            error_type: "auth",
            is_retryable: false,
            user_message: "Session expired, please log in again.",
          });
          throw new Error("Session expired");
        }
        if (res.status === 403) {
          onError({
            error: "Permission denied",
            error_type: "auth",
            is_retryable: false,
            user_message: "You don't have permission to perform this action.",
          });
          throw new Error("Permission denied");
        }
        if (!res.ok || !res.body) {
          onError({
            error: `Stream failed: ${res.status}`,
            error_type: "network",
            is_retryable: true,
            user_message: "Connection to the server failed. Please try again.",
          });
          throw new Error(`Stream failed: ${res.status}`);
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let gotResult = false;
        let gotError = false;
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          resetIdleTimer();
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop() || "";
          for (const part of parts) {
            const eventMatch = part.match(/^event:\s*([\w-]+)\ndata:\s*(.+)$/s);
            if (!eventMatch) continue;
            const [, eventType, jsonStr] = eventMatch;
            try {
              const parsed = JSON.parse(jsonStr);
              if (eventType === "token") onToken?.((parsed as { chunk: string }).chunk ?? "");
              else if (eventType === "thinking") onThinking?.(parsed);
              else if (eventType === "step") onStep(parsed);
              else if (eventType === "tool_call") onToolCall?.(parsed);
              else if (eventType === "agent_start" || eventType === "agent_end") onStep(parsed);
              else if (eventType === "result") {
                gotResult = true;
                onResult(parsed as ChatResponse);
              } else if (eventType === "error") {
                gotError = true;
                onError(parsed as StreamError);
              } else if (eventType === "session_rotated") {
                onSessionRotated?.(parsed as SessionRotatedEvent);
              } else if (PIPELINE_EVENTS.has(eventType)) {
                onPipelineEvent?.(eventType, parsed);
              }
            } catch {
              /* skip malformed */
            }
          }
        }
        if (!gotResult && !gotError) {
          onError({
            error: "Stream ended unexpectedly",
            error_type: "network",
            is_retryable: true,
            user_message: "The response ended unexpectedly. Please try again.",
          });
        }
      })
      .catch((err) => {
        if (idleTimer) clearTimeout(idleTimer);
        if (
          (err instanceof DOMException && err.name === "AbortError") ||
          (err &&
            typeof err === "object" &&
            "name" in err &&
            (err as { name: string }).name === "AbortError")
        ) {
          if (String(err.message || err).includes("idle timeout")) {
            onError({
              error: "Stream timed out",
              error_type: "timeout",
              is_retryable: true,
              user_message: "The response timed out. Please try again.",
            });
          }
          return;
        }
        onError({
          error: String(err),
          error_type: "network",
          is_retryable: true,
          user_message: "An unexpected error occurred. Please try again.",
        });
      })
      .finally(() => {
        if (idleTimer) clearTimeout(idleTimer);
      });
    return Object.assign(ctrl, { done: streamPromise });
  },
};
