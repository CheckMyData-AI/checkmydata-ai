"use client";

import { useEffect, useRef } from "react";
import { api } from "@/lib/api";
import * as storage from "@/lib/safe-storage";
import { useAppStore, getPersistedId } from "@/stores/app-store";
import type { ChatMessage } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";

function mapMessages(msgs: { id: string; role: string; content: string; metadata_json?: string | null; tool_calls_json?: string | null; user_rating?: number | null; created_at: string }[]): ChatMessage[] {
  return msgs.map((m) => {
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
}

function isAccessError(err: unknown): boolean {
  if (!(err instanceof Error)) return false;
  const msg = err.message;
  return (
    msg.includes("403") ||
    msg.includes("404") ||
    msg.includes("don't have permission") ||
    msg.includes("not found") ||
    msg.includes("Not a member")
  );
}

let _restoreSeq = 0;

/** Invalidate any in-flight restore (call when user explicitly switches project). */
export function invalidateRestore() {
  _restoreSeq++;
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

    const seq = ++_restoreSeq;
    const signal = { cancelled: false };
    const isStale = () => signal.cancelled || seq !== _restoreSeq;

    (async () => {
      try {
        const [projects, project] = await Promise.all([
          api.projects.list(),
          api.projects.get(projectId).catch(() => null),
        ]);

        if (isStale()) return;

        store.setProjects(projects);

        if (!project) {
          storage.removeItem("active_project_id");
          storage.removeItem("active_connection_id");
          storage.removeItem("active_session_id");
          return;
        }

        store.setActiveProject(project);
        store.setUserRole(project.user_role || null);

        const [conns, sessions] = await Promise.all([
          api.connections.listByProject(project.id),
          api.chat.listSessions(project.id),
        ]);

        if (isStale()) return;

        store.setConnections(conns);
        store.setChatSessions(sessions);

        const restoredConn =
          (connectionId && conns.find((c) => c.id === connectionId)) || conns[0] || null;
        store.setActiveConnection(restoredConn);

        if (sessions.length === 0) {
          try {
            const welcome = await api.chat.ensureWelcome(project.id, restoredConn?.id);
            if (isStale()) return;
            const welcomeSession = { id: welcome.id, project_id: welcome.project_id, title: welcome.title, connection_id: welcome.connection_id };
            store.setChatSessions([welcomeSession]);
            store.setActiveSession(welcomeSession);
            const msgs = await api.chat.getMessages(welcome.id);
            if (isStale()) return;
            store.setMessages(mapMessages(msgs));
          } catch { /* welcome session is best-effort */ }
        } else if (sessionId) {
          const session = sessions.find((s) => s.id === sessionId);
          if (session) {
            store.setActiveSession(session);
            try {
              const msgs = await api.chat.getMessages(sessionId);
              if (isStale()) return;
              store.setMessages(mapMessages(msgs));
            } catch {
              storage.removeItem("active_session_id");
            }
          } else {
            storage.removeItem("active_session_id");
          }
        }
      } catch (err) {
        if (isStale()) return;
        if (isAccessError(err)) {
          toast("You no longer have access to the previous project", "error");
          storage.removeItem("active_project_id");
          storage.removeItem("active_connection_id");
          storage.removeItem("active_session_id");
        } else {
          toast(
            "Failed to restore session — will retry on next refresh",
            "error",
          );
          ran.current = false;
        }
      } finally {
        if (!isStale()) {
          store.setRestoringState(false);
        }
      }
    })();

    return () => { signal.cancelled = true; };
  }, [isAuthenticated]);
}
