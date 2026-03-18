"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import type { ChatMessage } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";
import { confirmAction } from "@/components/ui/ConfirmModal";
import { Icon } from "@/components/ui/Icon";
import { ActionButton } from "@/components/ui/ActionButton";

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

  if (!activeProject || chatSessions.length === 0) return null;

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
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
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
      useAppStore.setState((state) => ({
        chatSessions: state.chatSessions.filter((s) => s.id !== sessionId),
        ...(state.activeSession?.id === sessionId
          ? { activeSession: null, messages: [] }
          : {}),
      }));
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

  return (
    <div className="space-y-1.5 px-1">
      <div className="flex justify-end px-1">
        <button
          onClick={handleNewChat}
          className="flex items-center gap-1 text-[11px] text-accent hover:text-accent-hover transition-colors"
        >
          <Icon name="plus" size={12} />
          New Chat
        </button>
      </div>
      <div className="space-y-0.5 max-h-48 overflow-y-auto overflow-x-hidden sidebar-scroll">
        {chatSessions.map((s) => (
          <div
            key={s.id}
            className={`group rounded-lg transition-colors ${
              activeSession?.id === s.id
                ? "bg-surface-2"
                : "hover:bg-surface-2/50"
            }`}
          >
            <button
              onClick={() => handleSelect(s.id)}
              disabled={loadingSession === s.id}
              className="w-full flex items-center gap-2 text-left px-2.5 py-2"
            >
              <Icon
                name="message-square"
                size={12}
                className={`shrink-0 ${
                  activeSession?.id === s.id
                    ? "text-accent"
                    : "text-text-muted"
                }`}
              />
              <span
                className={`text-xs truncate ${
                  activeSession?.id === s.id
                    ? "text-text-primary font-medium"
                    : "text-text-secondary"
                }`}
              >
                {loadingSession === s.id ? (
                  <span className="animate-pulse text-text-muted">
                    Loading...
                  </span>
                ) : (
                  s.title
                )}
              </span>
            </button>
            <div className="invisible group-hover:visible focus-within:visible flex items-center gap-1 px-2.5 pb-1.5 pt-0.5">
              <ActionButton
                icon="trash"
                title="Delete session"
                onClick={(e) => handleDelete(e, s.id)}
                variant="danger"
                size="sm"
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
