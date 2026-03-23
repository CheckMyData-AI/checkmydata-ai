"use client";

import { useEffect, useRef } from "react";
import { api } from "@/lib/api";
import { useAppStore, getPersistedId } from "@/stores/app-store";
import type { ChatMessage } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";

function isAccessError(err: unknown): boolean {
  if (!(err instanceof Error)) return false;
  return err.message.includes("403") || err.message.includes("404");
}

export function useRestoreState(isAuthenticated: boolean) {
  const ran = useRef(false);

  useEffect(() => {
    if (!isAuthenticated) {
      ran.current = false;
      return;
    }
    if (ran.current) return;
    ran.current = true;

    const projectId = getPersistedId("active_project_id");
    if (!projectId) return;

    const connectionId = getPersistedId("active_connection_id");
    const sessionId = getPersistedId("active_session_id");

    const store = useAppStore.getState();
    store.setRestoringState(true);

    const signal = { cancelled: false };

    (async () => {
      try {
        const [projects, project] = await Promise.all([
          api.projects.list(),
          api.projects.get(projectId).catch(() => null),
        ]);

        if (signal.cancelled) return;

        store.setProjects(projects);

        if (!project) {
          localStorage.removeItem("active_project_id");
          localStorage.removeItem("active_connection_id");
          localStorage.removeItem("active_session_id");
          return;
        }

        store.setActiveProject(project);
        store.setUserRole(project.user_role || null);

        const [conns, sessions] = await Promise.all([
          api.connections.listByProject(project.id),
          api.chat.listSessions(project.id),
        ]);

        if (signal.cancelled) return;

        store.setConnections(conns);
        store.setChatSessions(sessions);

        const restoredConn =
          (connectionId && conns.find((c) => c.id === connectionId)) || conns[0] || null;
        store.setActiveConnection(restoredConn);

        if (sessionId) {
          const session = sessions.find((s) => s.id === sessionId);
          if (session) {
            store.setActiveSession(session);
            try {
              const msgs = await api.chat.getMessages(sessionId);
              if (signal.cancelled) return;
              const mapped: ChatMessage[] = msgs.map((m) => {
                let meta: Record<string, unknown> = {};
                try { meta = m.metadata_json ? JSON.parse(m.metadata_json) : {}; } catch { /* malformed metadata */ }
                return {
                  id: m.id,
                  role: m.role as "user" | "assistant" | "system",
                  content: m.content,
                  query: (meta.query as string) || undefined,
                  queryExplanation: (meta.query_explanation as string) || undefined,
                  visualization: (meta.visualization as Record<string, unknown>) ?? undefined,
                  error: (meta.error as string) || undefined,
                  metadataJson: m.metadata_json || undefined,
                  stalenessWarning: (meta.staleness_warning as string) || undefined,
                  responseType: (meta.response_type as "text" | "sql_result" | "knowledge" | "error") || undefined,
                  userRating: m.user_rating ?? undefined,
                  toolCallsJson: m.tool_calls_json || undefined,
                  rawResult: (meta.raw_result as { columns: string[]; rows: unknown[][]; total_rows: number }) ?? undefined,
                  timestamp: new Date(m.created_at).getTime(),
                };
              });
              store.setMessages(mapped);
            } catch {
              localStorage.removeItem("active_session_id");
            }
          } else {
            localStorage.removeItem("active_session_id");
          }
        }
      } catch (err) {
        if (signal.cancelled) return;
        if (isAccessError(err)) {
          toast("You no longer have access to the previous project", "error");
          localStorage.removeItem("active_project_id");
          localStorage.removeItem("active_connection_id");
          localStorage.removeItem("active_session_id");
        } else {
          toast(
            "Failed to restore session — will retry on next refresh",
            "error",
          );
          ran.current = false;
        }
      } finally {
        if (!signal.cancelled) {
          store.setRestoringState(false);
        }
      }
    })();

    return () => { signal.cancelled = true; };
  }, [isAuthenticated]);
}
