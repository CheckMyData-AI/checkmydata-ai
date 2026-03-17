"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { useAppStore } from "@/stores/app-store";
import { api, type ChatResponse } from "@/lib/api";
import type { WorkflowEvent } from "@/lib/sse";
import { ChatInput } from "./ChatInput";
import { ChatMessage } from "./ChatMessage";
import { ToolCallIndicator } from "./ToolCallIndicator";
import { StreamWorkflowProgress } from "../workflow/StreamWorkflowProgress";
import { LogToggleButton } from "../log/LogPanel";
import { ReadinessGate, ReadinessBanner } from "./ReadinessGate";

export function ChatPanel() {
  const {
    activeProject,
    activeConnection,
    activeSession,
    messages,
    isThinking,
    chatMode,
    activeToolCalls,
    setActiveSession,
    addMessage,
    updateMessageId,
    setThinking,
    setLoading,
    addToolCall,
    clearToolCalls,
  } = useAppStore();

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [streamSteps, setStreamSteps] = useState<WorkflowEvent[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const [readinessBypassed, setReadinessBypassed] = useState(false);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const canChat = activeProject && (activeConnection || chatMode === "knowledge_only");

  const handleSend = useCallback(
    async (content: string) => {
      if (!activeProject) return;

      const userMsg = {
        id: crypto.randomUUID(),
        role: "user" as const,
        content,
        timestamp: Date.now(),
      };
      addMessage(userMsg);
      setThinking(true);
      setLoading(true);
      setStreamSteps([]);
      clearToolCalls();

      const ctrl = api.chat.askStream(
        {
          project_id: activeProject.id,
          connection_id: activeConnection?.id,
          message: content,
          session_id: activeSession?.id,
        },
        (step) => {
          setStreamSteps((prev) => [...prev, step as unknown as WorkflowEvent]);
        },
        (result: ChatResponse) => {
          if (!activeSession) {
            const newSession = {
              id: result.session_id,
              project_id: activeProject.id,
              title: content.slice(0, 50),
              connection_id: activeConnection?.id ?? null,
            };
            setActiveSession(newSession);
            useAppStore.setState((state) => ({
              chatSessions: [newSession, ...state.chatSessions],
            }));
            api.chat.generateTitle(result.session_id).then((updated) => {
              const updatedSession = {
                id: updated.id,
                project_id: updated.project_id,
                title: updated.title,
                connection_id: activeConnection?.id ?? null,
              };
              setActiveSession(updatedSession);
              useAppStore.setState((state) => ({
                chatSessions: state.chatSessions.map((s) =>
                  s.id === updated.id ? updatedSession : s,
                ),
              }));
            }).catch(() => { /* keep truncated title */ });
          }

          if (result.user_message_id) {
            updateMessageId(userMsg.id, result.user_message_id);
          }

          const ragSources = result.rag_sources ?? undefined;
          const tokenUsage = result.token_usage ?? undefined;

          const metadataObj: Record<string, unknown> = {
            query: result.query,
            query_explanation: result.query_explanation,
            viz_type: result.visualization?.type,
            visualization: result.visualization,
            error: result.error,
            workflow_id: result.workflow_id,
            rag_sources: ragSources,
            token_usage: tokenUsage,
            response_type: result.response_type,
            staleness_warning: result.staleness_warning,
          };

          const rawResult = (result as unknown as Record<string, unknown>)
            .raw_result as
            | { columns: string[]; rows: unknown[][]; total_rows: number }
            | undefined;

          addMessage({
            id: result.assistant_message_id || crypto.randomUUID(),
            role: "assistant",
            content: result.answer,
            query: result.query || undefined,
            queryExplanation: result.query_explanation || undefined,
            visualization: result.visualization,
            error: result.error,
            stalenessWarning: result.staleness_warning,
            responseType: result.response_type,
            metadataJson: JSON.stringify(metadataObj),
            rawResult: rawResult ?? undefined,
            timestamp: Date.now(),
          });

          setThinking(false);
          setLoading(false);
          setStreamSteps([]);
          clearToolCalls();
        },
        (error: string) => {
          addMessage({
            id: crypto.randomUUID(),
            role: "assistant",
            content: `Error: ${error}`,
            error,
            responseType: "error",
            timestamp: Date.now(),
          });
          setThinking(false);
          setLoading(false);
          setStreamSteps([]);
          clearToolCalls();
        },
        (toolEvent) => {
          addToolCall({
            step: (toolEvent as Record<string, string>).step ?? "",
            status: (toolEvent as Record<string, string>).status ?? "",
            detail: (toolEvent as Record<string, string>).detail ?? "",
          });
        },
      );
      abortRef.current = ctrl;
    },
    [activeProject, activeConnection, activeSession, chatMode, addMessage, updateMessageId, setThinking, setLoading, setActiveSession, clearToolCalls, addToolCall],
  );

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  if (!activeProject) {
    return (
      <div className="flex-1 flex items-center justify-center text-zinc-500">
        Select a project to start chatting
      </div>
    );
  }

  if (!canChat) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-zinc-500">
        <p>No database connection configured.</p>
        <button
          onClick={() => useAppStore.getState().setChatMode("knowledge_only")}
          className="px-4 py-2 bg-purple-600 text-white text-sm rounded-lg hover:bg-purple-500 transition-colors"
        >
          Chat with Knowledge Base
        </button>
      </div>
    );
  }

  const showReadinessGate = activeProject && activeConnection && messages.length === 0 && !readinessBypassed;

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {chatMode === "knowledge_only" && !activeConnection && (
        <div className="flex items-center justify-between px-6 py-1.5 bg-purple-900/20 border-b border-purple-800/30">
          <span className="text-xs text-purple-400">Knowledge Base Mode</span>
          <button
            onClick={() => useAppStore.getState().setChatMode("full")}
            className="text-[10px] text-purple-400 hover:text-purple-300"
          >
            Exit
          </button>
        </div>
      )}
      {readinessBypassed && activeProject && (
        <ReadinessBanner projectId={activeProject.id} />
      )}
      {showReadinessGate ? (
        <ReadinessGate
          projectId={activeProject.id}
          connectionId={activeConnection.id}
          onBypass={() => setReadinessBypassed(true)}
        />
      ) : (
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-zinc-500 text-sm mt-20">
            <p className="text-lg font-medium mb-2">
              {activeConnection ? "Ready to query" : "Knowledge Base Mode"}
            </p>
            {activeConnection ? (
              <p>
                Connected to{" "}
                <span className="text-zinc-300">{activeConnection.name}</span>{" "}
                ({activeConnection.db_type})
              </p>
            ) : (
              <p>Ask questions about your project documentation</p>
            )}
            <p className="mt-1">Ask a question about your data…</p>
          </div>
        )}
        {messages.map((msg, idx) => {
          const canRetry =
            msg.responseType === "error" &&
            idx === messages.length - 1 &&
            !isThinking;
          const prevUserMsg = canRetry
            ? [...messages].reverse().find((m) => m.role === "user")
            : undefined;
          return (
            <ChatMessage
              key={msg.id}
              message={msg}
              metadataJson={msg.metadataJson}
              onRetry={prevUserMsg ? () => handleSend(prevUserMsg.content) : undefined}
            />
          );
        })}
        {isThinking && (
          <div className="flex gap-3">
            <div className="bg-zinc-800 rounded-xl px-4 py-3 space-y-2">
              {activeToolCalls.length > 0 ? (
                <ToolCallIndicator events={activeToolCalls} />
              ) : streamSteps.length > 0 ? (
                <StreamWorkflowProgress events={streamSteps} compact />
              ) : (
                <div className="flex gap-1">
                  <span className="w-2 h-2 bg-zinc-500 rounded-full animate-bounce" />
                  <span className="w-2 h-2 bg-zinc-500 rounded-full animate-bounce [animation-delay:0.1s]" />
                  <span className="w-2 h-2 bg-zinc-500 rounded-full animate-bounce [animation-delay:0.2s]" />
                </div>
              )}
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      )}
      {!showReadinessGate && (
        <ChatInput onSend={handleSend} disabled={isThinking} rightSlot={<LogToggleButton />} />
      )}
    </div>
  );
}
