"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import type { ChatMessage } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";

export function ChatSessionList() {
  const {
    activeProject,
    chatSessions,
    activeSession,
    setActiveSession,
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

    try {
      const msgs = await api.chat.getMessages(sessionId);
      const mapped: ChatMessage[] = msgs.map((m) => {
        const meta = m.metadata_json ? JSON.parse(m.metadata_json) : {};
        return {
          id: m.id,
          role: m.role as "user" | "assistant" | "system",
          content: m.content,
          query: meta.query || undefined,
          visualization: meta.visualization ?? undefined,
          error: meta.error || undefined,
          metadataJson: m.metadata_json || undefined,
          timestamp: new Date(m.created_at).getTime(),
        };
      });
      setMessages(mapped);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load session messages", "error");
    } finally {
      setLoadingSession(null);
    }
  };

  const handleDelete = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    try {
      await api.chat.deleteSession(sessionId);
      useAppStore.setState((state) => ({
        chatSessions: state.chatSessions.filter((s) => s.id !== sessionId),
        ...(state.activeSession?.id === sessionId
          ? { activeSession: null, messages: [] }
          : {}),
      }));
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to delete session", "error");
    }
  };

  const handleNewChat = () => {
    setActiveSession(null);
    setMessages([]);
  };

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <button
          onClick={handleNewChat}
          className="text-xs text-blue-400 hover:text-blue-300"
        >
          + New Chat
        </button>
      </div>
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {chatSessions.map((s) => (
          <div key={s.id} className="flex items-center group">
            <button
              onClick={() => handleSelect(s.id)}
              disabled={loadingSession === s.id}
              className={`flex-1 text-left px-3 py-1.5 rounded-md text-xs transition-colors truncate ${
                activeSession?.id === s.id
                  ? "bg-zinc-800 text-zinc-100"
                  : "text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-300"
              }`}
            >
              {loadingSession === s.id ? (
                <span className="animate-pulse">Loading...</span>
              ) : (
                s.title
              )}
            </button>
            <button
              onClick={(e) => handleDelete(e, s.id)}
              className="text-xs text-zinc-600 hover:text-red-400 px-1 opacity-0 group-hover:opacity-100 transition-opacity"
              title="Delete session"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
