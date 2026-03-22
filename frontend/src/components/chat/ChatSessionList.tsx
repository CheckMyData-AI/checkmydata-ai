"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import type { ChatMessage } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";
import { confirmAction } from "@/components/ui/ConfirmModal";
import { Icon } from "@/components/ui/Icon";
import { ActionButton } from "@/components/ui/ActionButton";

const VISIBLE_CAP = 5;

export function ChatSessionList() {
  const {
    activeProject,
    connections,
    chatSessions,
    activeSession,
    setActiveSession,
    setActiveConnection,
    setMessages,
    setChatSessions,
  } = useAppStore();

  const [loadingSession, setLoadingSession] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  if (!activeProject) return null;
  if (chatSessions.length === 0) {
    return (
      <div className="px-3 py-4 text-center">
        <p className="text-xs text-text-muted">No chats yet</p>
      </div>
    );
  }

  const handleSelect = async (sessionId: string) => {
    const session = chatSessions.find((s) => s.id === sessionId);
    if (!session) return;

    setActiveSession(session);
    setLoadingSession(sessionId);

    if (session.connection_id) {
      const conn = connections.find((c) => c.id === session.connection_id);
      if (conn) setActiveConnection(conn);
    }

    try {
      const msgs = await api.chat.getMessages(sessionId);
      const mapped: ChatMessage[] = msgs.map((m) => {
        let meta: any = {};
        try {
          meta = m.metadata_json ? JSON.parse(m.metadata_json) : {};
        } catch {
          /* malformed metadata */
        }
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
      setMessages(mapped);
    } catch (err) {
      toast(
        err instanceof Error
          ? err.message
          : "Failed to load session messages",
        "error",
      );
    } finally {
      setLoadingSession(null);
    }
  };

  const handleDelete = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    if (!(await confirmAction("Delete this chat session?"))) return;
    try {
      await api.chat.deleteSession(sessionId);
      const wasActive = useAppStore.getState().activeSession?.id === sessionId;
      const current = useAppStore.getState().chatSessions;
      setChatSessions(current.filter((s) => s.id !== sessionId));
      if (wasActive) {
        setActiveSession(null);
        setMessages([]);
      }
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Failed to delete session",
        "error",
      );
    }
  };

  const handleNewChat = () => {
    setActiveSession(null);
    setMessages([]);
  };

  const visibleSessions = showAll
    ? chatSessions
    : chatSessions.slice(0, VISIBLE_CAP);
  const hasMore = chatSessions.length > VISIBLE_CAP;

  return (
    <div className="px-1">
      <div className="flex justify-end px-1 mb-1">
        <button
          onClick={handleNewChat}
          className="flex items-center gap-1 text-[11px] text-accent hover:text-accent-hover transition-colors"
        >
          <Icon name="plus" size={12} />
          New Chat
        </button>
      </div>
      <div>
        {visibleSessions.map((s) => {
          const isActive = activeSession?.id === s.id;
          return (
            <div
              key={s.id}
              className={`group relative flex items-center gap-2 pl-3 pr-1.5 py-1.5 rounded-md transition-colors cursor-pointer ${
                isActive ? "bg-surface-1" : "hover:bg-surface-1"
              }`}
              onClick={() => handleSelect(s.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  handleSelect(s.id);
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
                {loadingSession === s.id ? (
                  <span className="animate-pulse text-text-muted">Loading...</span>
                ) : (
                  s.title
                )}
              </span>
              <div className="shrink-0 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity duration-150">
                <ActionButton
                  icon="trash"
                  title="Delete session"
                  onClick={(e) => handleDelete(e, s.id)}
                  variant="danger"
                  size="xs"
                />
              </div>
            </div>
          );
        })}
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
