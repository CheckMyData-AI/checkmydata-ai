"use client";

import { useEffect, useRef } from "react";
import { api } from "@/lib/api";
import { useAppStore, getPersistedId } from "@/stores/app-store";
import type { ChatMessage } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";

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

    (async () => {
      try {
        const [projects, project] = await Promise.all([
          api.projects.list(),
          api.projects.get(projectId).catch(() => null),
        ]);

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
              const mapped: ChatMessage[] = msgs.map((m) => {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                let meta: any = {};
                try { meta = m.metadata_json ? JSON.parse(m.metadata_json) : {}; } catch { /* malformed metadata */ }
                return {
                  id: m.id,
                  role: m.role as "user" | "assistant" | "system",
                  content: m.content,
                  query: meta.query || undefined,
                  queryExplanation: meta.query_explanation || undefined,
                  visualization: meta.visualization ?? undefined,
                  error: meta.error || undefined,
                  metadataJson: m.metadata_json || undefined,
                  stalenessWarning: meta.staleness_warning || undefined,
                  responseType: meta.response_type || undefined,
                  userRating: m.user_rating ?? undefined,
                  toolCallsJson: m.tool_calls_json || undefined,
                  rawResult: meta.raw_result ?? undefined,
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
        const msg =
          err instanceof Error && err.message.includes("403")
            ? "You no longer have access to the previous project"
            : "Failed to restore previous session — please select a project";
        toast(msg, "error");
        localStorage.removeItem("active_project_id");
        localStorage.removeItem("active_connection_id");
        localStorage.removeItem("active_session_id");
      } finally {
        store.setRestoringState(false);
      }
    })();
  }, [isAuthenticated]);
}
