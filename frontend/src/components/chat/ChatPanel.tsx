"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { useAppStore } from "@/stores/app-store";
import { api, type ChatResponse } from "@/lib/api";
import type { WorkflowEvent } from "@/lib/sse";
import { ChatInput } from "./ChatInput";
import { ChatMessage } from "./ChatMessage";
import { StreamWorkflowProgress } from "../workflow/StreamWorkflowProgress";

export function ChatPanel() {
  const {
    activeProject,
    activeConnection,
    activeSession,
    messages,
    isThinking,
    setActiveSession,
    addMessage,
    setThinking,
    setLoading,
  } = useAppStore();

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [streamSteps, setStreamSteps] = useState<WorkflowEvent[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = useCallback(
    async (content: string) => {
      if (!activeProject || !activeConnection) return;

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

      const ctrl = api.chat.askStream(
        {
          project_id: activeProject.id,
          connection_id: activeConnection.id,
          message: content,
          session_id: activeSession?.id,
        },
        (step) => {
          setStreamSteps((prev) => [...prev, step as unknown as WorkflowEvent]);
        },
        (result: ChatResponse) => {
          if (!activeSession) {
            setActiveSession({
              id: result.session_id,
              project_id: activeProject.id,
              title: content.slice(0, 50),
            });
            api.chat.generateTitle(result.session_id).then((updated) => {
              setActiveSession({
                id: updated.id,
                project_id: updated.project_id,
                title: updated.title,
              });
            }).catch(() => { /* keep truncated title */ });
          }

          const ragSources = (result as Record<string, unknown>).rag_sources as
            | Array<{ source_path: string; distance?: number; doc_type?: string }>
            | undefined;
          const attempts = (result as Record<string, unknown>).attempts as
            | Array<Record<string, unknown>>
            | undefined;
          const totalAttempts = (result as Record<string, unknown>).total_attempts as
            | number
            | undefined;

          const tokenUsage = (result as Record<string, unknown>).token_usage as
            | Record<string, number>
            | undefined;

          const metadataObj: Record<string, unknown> = {
            query: result.query,
            viz_type: result.visualization?.type,
            error: result.error,
            workflow_id: result.workflow_id,
            rag_sources: ragSources,
            attempts,
            total_attempts: totalAttempts,
            token_usage: tokenUsage,
          };

          addMessage({
            id: crypto.randomUUID(),
            role: "assistant",
            content: result.answer,
            query: result.query || undefined,
            queryExplanation: result.query_explanation || undefined,
            visualization: result.visualization,
            error: result.error,
            stalenessWarning: result.staleness_warning,
            metadataJson: JSON.stringify(metadataObj),
            timestamp: Date.now(),
          });

          setThinking(false);
          setLoading(false);
          setStreamSteps([]);
        },
        (error: string) => {
          addMessage({
            id: crypto.randomUUID(),
            role: "assistant",
            content: `Error: ${error}`,
            error,
            timestamp: Date.now(),
          });
          setThinking(false);
          setLoading(false);
          setStreamSteps([]);
        },
      );
      abortRef.current = ctrl;
    },
    [activeProject, activeConnection, activeSession, addMessage, setThinking, setLoading, setActiveSession],
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

  if (!activeConnection) {
    return (
      <div className="flex-1 flex items-center justify-center text-zinc-500">
        Configure a database connection for this project
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-zinc-500 text-sm mt-20">
            <p className="text-lg font-medium mb-2">Ready to query</p>
            <p>
              Connected to{" "}
              <span className="text-zinc-300">{activeConnection.name}</span>{" "}
              ({activeConnection.db_type})
            </p>
            <p className="mt-1">Ask a question about your data...</p>
          </div>
        )}
        {messages.map((msg) => (
          <ChatMessage key={msg.id} message={msg} metadataJson={msg.metadataJson} />
        ))}
        {isThinking && (
          <div className="flex gap-3">
            <div className="bg-zinc-800 rounded-xl px-4 py-3 space-y-2">
              {streamSteps.length > 0 ? (
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
      <ChatInput onSend={handleSend} disabled={isThinking} />
    </div>
  );
}
