"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import type { ChatMessage, SQLResultBlock } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";
import { confirmAction } from "@/components/ui/ConfirmModal";
import { Icon } from "@/components/ui/Icon";
import { ActionButton } from "@/components/ui/ActionButton";

const VISIBLE_CAP = 5;

export function mapDtoToMessages(msgs: { id: string; role: string; content: string; metadata_json?: string | null; tool_calls_json?: string | null; user_rating?: number | null; created_at: string }[]): ChatMessage[] {
  return msgs.map((m) => {
    let meta: Record<string, unknown> = {};
    try {
      meta = m.metadata_json ? JSON.parse(m.metadata_json) : {};
    } catch {
      /* malformed metadata */
    }
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
      sqlResults: _hydrateSqlResults(meta.sql_results),
    };
  });
}

function _hydrateSqlResults(raw: unknown): SQLResultBlock[] | undefined {
  if (!Array.isArray(raw) || raw.length === 0) return undefined;
  return raw.map((sr: Record<string, unknown>) => ({
    query: (sr.query as string) ?? undefined,
    queryExplanation: (sr.query_explanation as string) ?? undefined,
    visualization: (sr.visualization as Record<string, unknown>) ?? undefined,
    rawResult: (sr.raw_result as { columns: string[]; rows: unknown[][]; total_rows: number }) ?? undefined,
    insights: (sr.insights as Array<{ type: string; title: string; description: string; confidence: number }>) ?? undefined,
  }));
}

interface SessionItemProps {
  session: { id: string; title: string };
  isActive: boolean;
  isLoading: boolean;
  onSelect: (id: string) => void;
  onDelete: (e: React.MouseEvent, id: string) => void;
}

const SessionItem = memo(function SessionItem({
  session,
  isActive,
  isLoading,
  onSelect,
  onDelete,
}: SessionItemProps) {
  return (
    <div
      className={`group relative flex items-center gap-2 pl-3 pr-1.5 py-1.5 rounded-md transition-colors cursor-pointer ${
        isActive ? "bg-surface-1" : "hover:bg-surface-1"
      }`}
      onClick={() => onSelect(session.id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(session.id);
        }
      }}
    >
      {isActive && (
        <div className="absolute left-0.5 top-1/4 bottom-1/4 w-0.5 bg-accent rounded-full" />
      )}
      <Icon
        name="message-square"
        size={12}
        className={`shrink-0 ${isActive ? "text-accent" : "text-text-muted"}`}
      />
      <span
        className={`flex-1 min-w-0 text-xs truncate ${
          isActive ? "text-text-primary font-medium" : "text-text-secondary"
        }`}
      >
        {isLoading ? (
          <span className="animate-pulse text-text-muted">Loading...</span>
        ) : (
          session.title
        )}
      </span>
      <div className="shrink-0 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity duration-150">
        <ActionButton
          icon="trash"
          title="Delete session"
          onClick={(e) => onDelete(e, session.id)}
          variant="danger"
          size="xs"
        />
      </div>
    </div>
  );
});

interface ChatSessionListProps {
  createRequested?: boolean;
  onCreateHandled?: () => void;
}

export function ChatSessionList({ createRequested, onCreateHandled }: ChatSessionListProps) {
  const activeProject = useAppStore((s) => s.activeProject);
  const activeConnection = useAppStore((s) => s.activeConnection);
  const connections = useAppStore((s) => s.connections);
  const chatSessions = useAppStore((s) => s.chatSessions);
  const activeSession = useAppStore((s) => s.activeSession);
  const setActiveSession = useAppStore((s) => s.setActiveSession);
  const setActiveConnection = useAppStore((s) => s.setActiveConnection);
  const setSessionMessages = useAppStore((s) => s.setSessionMessages);
  const setChatSessions = useAppStore((s) => s.setChatSessions);

  const [loadingSession, setLoadingSession] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const creatingRef = useRef(false);
  const fetchAbortRef = useRef<AbortController | null>(null);

  const handleSelect = useCallback(async (sessionId: string) => {
    const session = chatSessions.find((s) => s.id === sessionId);
    if (!session || session.id === useAppStore.getState().activeSession?.id) return;

    fetchAbortRef.current?.abort();
    const ctrl = new AbortController();
    fetchAbortRef.current = ctrl;

    setActiveSession(session);

    if (session.connection_id) {
      const conn = connections.find((c) => c.id === session.connection_id);
      if (conn) setActiveConnection(conn);
    }

    if (useAppStore.getState().hasSessionCache(sessionId)) {
      setLoadingSession(null);
      return;
    }

    setLoadingSession(sessionId);
    try {
      const msgs = await api.chat.getMessages(sessionId);
      if (ctrl.signal.aborted) return;
      setSessionMessages(sessionId, mapDtoToMessages(msgs));
    } catch (err) {
      if (ctrl.signal.aborted) return;
      toast(
        err instanceof Error
          ? err.message
          : "Failed to load session messages",
        "error",
      );
    } finally {
      if (!ctrl.signal.aborted) setLoadingSession(null);
    }
  }, [chatSessions, connections, setActiveSession, setActiveConnection, setSessionMessages]);

  const handleDelete = useCallback(async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    if (!(await confirmAction("Delete this chat session?"))) return;
    try {
      await api.chat.deleteSession(sessionId);
      const wasActive = useAppStore.getState().activeSession?.id === sessionId;
      const current = useAppStore.getState().chatSessions;
      setChatSessions(current.filter((s) => s.id !== sessionId));
      useAppStore.setState((state) => {
        const { [sessionId]: _, ...rest } = state.messagesBySession;
        return { messagesBySession: rest };
      });
      if (wasActive) {
        setActiveSession(null);
      }
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Failed to delete session",
        "error",
      );
    }
  }, [setChatSessions, setActiveSession]);

  const handleNewChat = useCallback(async () => {
    if (!activeProject || creatingRef.current) return;
    creatingRef.current = true;
    try {
      const session = await api.chat.createSession({
        project_id: activeProject.id,
        connection_id: activeConnection?.id ?? undefined,
      });
      const newSession = {
        id: session.id,
        project_id: session.project_id,
        title: session.title,
        connection_id: session.connection_id ?? null,
      };
      useAppStore.setState((state) => ({
        chatSessions: [newSession, ...state.chatSessions],
      }));
      setActiveSession(newSession);
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Failed to create chat",
        "error",
      );
    } finally {
      creatingRef.current = false;
    }
  }, [activeProject, activeConnection, setActiveSession]);

  useEffect(() => {
    if (createRequested) {
      handleNewChat();
      onCreateHandled?.();
    }
  }, [createRequested, onCreateHandled, handleNewChat]);

  if (!activeProject) return null;
  if (chatSessions.length === 0) {
    return (
      <div className="px-3 py-4 text-center">
        <p className="text-xs text-text-muted">No chats yet</p>
      </div>
    );
  }

  const visibleSessions = showAll
    ? chatSessions
    : chatSessions.slice(0, VISIBLE_CAP);
  const hasMore = chatSessions.length > VISIBLE_CAP;

  return (
    <div className="px-1">
      <div>
        {visibleSessions.map((s) => (
          <SessionItem
            key={s.id}
            session={s}
            isActive={activeSession?.id === s.id}
            isLoading={loadingSession === s.id}
            onSelect={handleSelect}
            onDelete={handleDelete}
          />
        ))}
      </div>
      {hasMore && (
        <button
          onClick={() => setShowAll((v) => !v)}
          className="w-full text-[10px] text-text-muted hover:text-accent py-1 transition-colors"
        >
          {showAll ? "Show less" : `Show all ${chatSessions.length}`} →
        </button>
      )}
    </div>
  );
}
