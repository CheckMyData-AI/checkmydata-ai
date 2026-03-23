"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { useAppStore } from "@/stores/app-store";
import { api, type ChatResponse, type StreamError, type QuerySuggestion, type CostEstimate } from "@/lib/api";
import type { WorkflowEvent } from "@/lib/sse";
import { toast } from "@/stores/toast-store";
import { ChatInput } from "./ChatInput";
import { ChatMessage } from "./ChatMessage";
import { SuggestionChips } from "./SuggestionChips";
import { ToolCallIndicator } from "./ToolCallIndicator";
import { ThinkingLog } from "./ThinkingLog";
import { StageProgress, type PipelineStage } from "./StageProgress";
import { ReadinessGate, ReadinessBanner } from "./ReadinessGate";
import { ConnectionHealth } from "@/components/connections/ConnectionHealth";
import { CostEstimator } from "./CostEstimator";
import { ContextBudgetIndicator } from "./ContextBudgetIndicator";

export function ChatPanel() {
  const activeProject = useAppStore((s) => s.activeProject);
  const activeConnection = useAppStore((s) => s.activeConnection);
  const activeSession = useAppStore((s) => s.activeSession);
  const messages = useAppStore((s) => s.messages);
  const isThinking = useAppStore((s) => s.isThinking);
  const chatMode = useAppStore((s) => s.chatMode);
  const activeToolCalls = useAppStore((s) => s.activeToolCalls);
  const restoringState = useAppStore((s) => s.restoringState);
  const sessionTokens = useAppStore((s) => s.sessionTokens);
  const sessionCost = useAppStore((s) => s.sessionCost);
  const setActiveSession = useAppStore((s) => s.setActiveSession);
  const addMessage = useAppStore((s) => s.addMessage);
  const updateMessageId = useAppStore((s) => s.updateMessageId);
  const setThinking = useAppStore((s) => s.setThinking);
  const setLoading = useAppStore((s) => s.setLoading);
  const addToolCall = useAppStore((s) => s.addToolCall);
  const clearToolCalls = useAppStore((s) => s.clearToolCalls);
  const bumpRulesVersion = useAppStore((s) => s.bumpRulesVersion);
  const addSessionUsage = useAppStore((s) => s.addSessionUsage);
  const resetSessionUsage = useAppStore((s) => s.resetSessionUsage);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [streamSteps, setStreamSteps] = useState<WorkflowEvent[]>([]);
  const [pipelineStages, setPipelineStages] = useState<PipelineStage[]>([]);
  const [pipelineRunId, setPipelineRunId] = useState<string | undefined>();
  const [checkpointStageId, setCheckpointStageId] = useState<string | undefined>();
  const [thinkingLog, setThinkingLog] = useState<string[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [thinkingStartTime, setThinkingStartTime] = useState<number>(0);
  const [suggestions, setSuggestions] = useState<QuerySuggestion[]>([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [costEstimate, setCostEstimate] = useState<CostEstimate | null>(null);
  const suggestionsRequested = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const handleEstimate = useCallback((e: CostEstimate | null) => setCostEstimate(e), []);
  const cachedReady = useAppStore((s) =>
    activeProject ? s.readinessCache[activeProject.id]?.ready : false
  );
  const [readinessBypassed, setReadinessBypassed] = useState(false);
  const [connHealthStatus, setConnHealthStatus] = useState<string>("unknown");
  const [reconnecting, setReconnecting] = useState(false);

  const handlePipelineEvent = useCallback(
    (eventType: string, event: Record<string, unknown>) => {
      const extra = (event.extra ?? {}) as Record<string, unknown>;
      switch (eventType) {
        case "plan": {
          const rawStages = (extra.stages ?? []) as Array<{
            id: string;
            description: string;
            tool: string;
            checkpoint: boolean;
          }>;
          setPipelineStages(
            rawStages.map((s) => ({
              id: s.id,
              description: s.description,
              tool: s.tool,
              checkpoint: s.checkpoint,
              status: "pending" as const,
            })),
          );
          break;
        }
        case "stage_start": {
          const sid = extra.stage_id as string;
          setPipelineStages((prev) =>
            prev.map((s) => (s.id === sid ? { ...s, status: "running" } : s)),
          );
          break;
        }
        case "stage_result":
        case "stage_complete": {
          const sid = extra.stage_id as string;
          const status = extra.status as string;
          setPipelineStages((prev) =>
            prev.map((s) =>
              s.id === sid
                ? {
                    ...s,
                    status: status === "error" ? "failed" : "passed",
                    rowCount: (extra.row_count as number) ?? s.rowCount,
                    columns: (extra.columns as string[]) ?? s.columns,
                    error: (extra.error as string) ?? undefined,
                  }
                : s,
            ),
          );
          break;
        }
        case "stage_validation": {
          const sid = extra.stage_id as string;
          const passed = extra.passed as boolean;
          if (!passed) {
            setPipelineStages((prev) =>
              prev.map((s) =>
                s.id === sid
                  ? {
                      ...s,
                      status: "failed",
                      warnings: (extra.warnings as string[]) ?? [],
                      error: ((extra.errors as string[]) ?? []).join("; "),
                    }
                  : s,
              ),
            );
          }
          break;
        }
        case "checkpoint": {
          const sid = extra.stage_id as string;
          setCheckpointStageId(sid);
          setPipelineStages((prev) =>
            prev.map((s) => (s.id === sid ? { ...s, status: "checkpoint" } : s)),
          );
          break;
        }
        case "stage_retry": {
          const sid = extra.stage_id as string;
          setPipelineStages((prev) =>
            prev.map((s) => (s.id === sid ? { ...s, status: "running" } : s)),
          );
          break;
        }
      }
    },
    [],
  );

  const handleThinkingEvent = useCallback(
    (event: Record<string, unknown>) => {
      const detail = (event.detail as string) ?? "";
      if (!detail) return;
      setThinkingLog((prev) => {
        const next = [...prev, detail];
        return next.length > 50 ? next.slice(-50) : next;
      });
    },
    [],
  );

  const handleToken = useCallback((chunk: string) => {
    setStreamingText((prev) => prev + chunk);
  }, []);

  const sendPipelineAction = useCallback(
    (action: string, modification?: string) => {
      if (!activeProject || !pipelineRunId || !activeSession) return;
      setCheckpointStageId(undefined);
      setThinking(true);
      setLoading(true);
      setThinkingLog([]);
      setStreamingText("");

      const ctrl = api.chat.askStream(
        {
          project_id: activeProject.id,
          connection_id: activeConnection?.id,
          message: modification || action,
          session_id: activeSession.id,
          pipeline_action: action,
          pipeline_run_id: pipelineRunId,
          modification,
        },
        (step) => setStreamSteps((prev) => {
          const next = [...prev, step as unknown as WorkflowEvent];
          return next.length > 100 ? next.slice(-100) : next;
        }),
        (result: ChatResponse) => {
          const vizConfig = (result as unknown as Record<string, unknown>).viz_config as Record<string, unknown> | undefined;
          if (vizConfig?.pipeline_run_id) {
            setPipelineRunId(vizConfig.pipeline_run_id as string);
          }

          addMessage({
            id: result.assistant_message_id || crypto.randomUUID(),
            role: "assistant",
            content: result.answer,
            query: result.query || undefined,
            queryExplanation: result.query_explanation || undefined,
            visualization: result.visualization,
            error: result.error,
            responseType: result.response_type,
            timestamp: Date.now(),
          });
          setThinking(false);
          setLoading(false);
          setStreamSteps([]);
          clearToolCalls();
          setThinkingLog([]);
          setStreamingText("");
          if (result.response_type !== "stage_checkpoint" && result.response_type !== "stage_failed") {
            setPipelineStages([]);
            setPipelineRunId(undefined);
          }
        },
        (streamErr: StreamError) => {
          addMessage({
            id: crypto.randomUUID(),
            role: "assistant",
            content: streamErr.user_message || streamErr.error || "An unexpected error occurred.",
            error: streamErr.error,
            responseType: "error",
            timestamp: Date.now(),
          });
          setThinking(false);
          setLoading(false);
          setStreamSteps([]);
          clearToolCalls();
          setThinkingLog([]);
          setStreamingText("");
        },
        (toolEvent) => {
          addToolCall({
            step: (toolEvent as Record<string, string>).step ?? "",
            status: (toolEvent as Record<string, string>).status ?? "",
            detail: (toolEvent as Record<string, string>).detail ?? "",
          });
        },
        handlePipelineEvent,
        handleThinkingEvent,
        handleToken,
      );
      abortRef.current = ctrl;
    },
    [activeProject, activeConnection, activeSession, pipelineRunId, addMessage, setThinking, setLoading, clearToolCalls, addToolCall, handlePipelineEvent, handleThinkingEvent, handleToken],
  );

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (
      messages.length === 0 &&
      activeProject &&
      activeConnection &&
      !suggestionsRequested.current
    ) {
      suggestionsRequested.current = true;
      setSuggestionsLoading(true);
      let cancelled = false;
      api.chat
        .suggestions(activeProject.id, activeConnection.id)
        .then((s) => { if (!cancelled) setSuggestions(s); })
        .catch(() => { if (!cancelled) { setSuggestions([]); toast("Could not load suggestions", "error"); } })
        .finally(() => { if (!cancelled) setSuggestionsLoading(false); });
      return () => { cancelled = true; };
    }
    if (messages.length > 0) {
      setSuggestions([]);
    }
  }, [messages.length, activeProject, activeConnection]);

  useEffect(() => {
    suggestionsRequested.current = false;
    setSuggestions([]);
    setConnHealthStatus("unknown");
  }, [activeConnection?.id]);

  useEffect(() => {
    resetSessionUsage();
  }, [activeSession?.id, resetSessionUsage]);

  const canChat = activeProject && (activeConnection || chatMode === "knowledge_only");

  const handleSend = useCallback(
    async (content: string) => {
      if (!activeProject) return;

      if (costEstimate && costEstimate.context_utilization_pct > 80) {
        toast("Context budget is nearly full. Large schemas may affect query quality.", "info");
      }

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
      setThinkingLog([]);
      setStreamingText("");
      setThinkingStartTime(Date.now());
      setPipelineStages([]);
      setPipelineRunId(undefined);
      setCheckpointStageId(undefined);

      const ctrl = api.chat.askStream(
        {
          project_id: activeProject.id,
          connection_id: activeConnection?.id,
          message: content,
          session_id: activeSession?.id,
        },
        (step) => {
          setStreamSteps((prev) => {
            const next = [...prev, step as unknown as WorkflowEvent];
            return next.length > 100 ? next.slice(-100) : next;
          });
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

          const suggestedFollowups = (result as unknown as Record<string, unknown>)
            .suggested_followups as string[] | undefined;

          const insights = (result as unknown as Record<string, unknown>)
            .insights as Array<{ type: string; title: string; description: string; confidence: number }> | undefined;

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
            suggested_followups: suggestedFollowups,
            insights: insights ?? [],
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
            clarificationData: result.clarification_data ?? undefined,
            verificationStatus: result.response_type === "sql_result" ? "unverified" : undefined,
          });

          if (result.rules_changed) {
            bumpRulesVersion();
          }

          if (result.token_usage) {
            const tu = result.token_usage;
            const totalTk = tu.total_tokens ?? ((tu.prompt_tokens ?? 0) + (tu.completion_tokens ?? 0));
            const costUsd = (tu as Record<string, unknown>).estimated_cost_usd as number | undefined;
            addSessionUsage(totalTk, costUsd ?? 0);
          }

          const vizConfig = (result as unknown as Record<string, unknown>).viz_config as Record<string, unknown> | undefined;
          if (vizConfig?.pipeline_run_id) {
            setPipelineRunId(vizConfig.pipeline_run_id as string);
          }

          setThinking(false);
          setLoading(false);
          setStreamSteps([]);
          clearToolCalls();
          setThinkingLog([]);
          setStreamingText("");

          if (
            result.response_type !== "stage_checkpoint" &&
            result.response_type !== "stage_failed"
          ) {
            setPipelineStages([]);
            setPipelineRunId(undefined);
          }
        },
        (streamErr: StreamError) => {
          const displayMsg = streamErr.user_message || streamErr.error || "An unexpected error occurred.";
          addMessage({
            id: crypto.randomUUID(),
            role: "assistant",
            content: displayMsg,
            error: streamErr.error,
            responseType: "error",
            isRetryable: streamErr.is_retryable !== false,
            timestamp: Date.now(),
          });
          setThinking(false);
          setLoading(false);
          setStreamSteps([]);
          clearToolCalls();
          setThinkingLog([]);
          setStreamingText("");
        },
        (toolEvent) => {
          addToolCall({
            step: (toolEvent as Record<string, string>).step ?? "",
            status: (toolEvent as Record<string, string>).status ?? "",
            detail: (toolEvent as Record<string, string>).detail ?? "",
          });
        },
        handlePipelineEvent,
        handleThinkingEvent,
        handleToken,
      );
      abortRef.current = ctrl;
    },
    [activeProject, activeConnection, activeSession, costEstimate, addMessage, updateMessageId, setThinking, setLoading, setActiveSession, clearToolCalls, addToolCall, bumpRulesVersion, addSessionUsage, handlePipelineEvent, handleThinkingEvent, handleToken],
  );

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
    setThinking(false);
    setLoading(false);
    clearToolCalls();
    setThinkingLog([]);
    setStreamingText((prev) => {
      if (prev) {
        addMessage({
          id: crypto.randomUUID(),
          role: "assistant",
          content: prev + "\n\n*(Generation stopped by user)*",
          timestamp: Date.now(),
        });
      }
      return "";
    });
  }, [setThinking, setLoading, clearToolCalls, addMessage]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  if (restoringState) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3">
        <div className="flex gap-1">
          <span className="w-2 h-2 bg-text-muted rounded-full animate-bounce" />
          <span className="w-2 h-2 bg-text-muted rounded-full animate-bounce [animation-delay:0.1s]" />
          <span className="w-2 h-2 bg-text-muted rounded-full animate-bounce [animation-delay:0.2s]" />
        </div>
        <p className="text-text-muted text-sm">Restoring your session…</p>
      </div>
    );
  }

  if (!activeProject) {
    return (
      <div className="flex-1 flex flex-col p-6 gap-4">
        <div className="animate-pulse bg-surface-2 rounded-lg h-4 w-3/4" />
        <div className="animate-pulse bg-surface-2 rounded-lg h-4 w-1/2" />
        <div className="animate-pulse bg-surface-2 rounded-lg h-4 w-2/3" />
        <p className="text-text-muted text-sm mt-4">Select a project to start chatting</p>
      </div>
    );
  }

  const showReadinessGate = messages.length === 0 && !readinessBypassed && !cachedReady;

  if (showReadinessGate) {
    return (
      <div className="flex-1 flex flex-col min-h-0">
        <div className="flex-1 overflow-x-hidden overflow-y-auto p-6 space-y-4">
          <ReadinessGate
            projectId={activeProject.id}
            connectionId={activeConnection?.id ?? null}
            onBypass={() => setReadinessBypassed(true)}
          />
        </div>
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
          aria-label="Chat with Knowledge Base"
        >
          Chat with Knowledge Base
        </button>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {chatMode === "knowledge_only" && !activeConnection && (
        <div className="flex items-center justify-between px-6 py-1.5 bg-purple-900/20 border-b border-purple-800/30">
          <span className="text-xs text-purple-400">Knowledge Base Mode</span>
          <button
            onClick={() => useAppStore.getState().setChatMode("full")}
            className="text-[10px] text-purple-400 hover:text-purple-300"
            aria-label="Exit Knowledge Base Mode"
          >
            Exit
          </button>
        </div>
      )}
      {readinessBypassed && activeProject && (
        <ReadinessBanner projectId={activeProject.id} />
      )}
      {activeConnection && (
        <div className="hidden">
          <ConnectionHealth
            connectionId={activeConnection.id}
            onStatusChange={setConnHealthStatus}
          />
        </div>
      )}
      {connHealthStatus === "degraded" && activeConnection && (
        <div className="flex items-center gap-2 px-6 py-1.5 bg-warning/10 border-b border-warning/20">
          <span className="w-1.5 h-1.5 rounded-full bg-warning shrink-0" />
          <span className="text-xs text-warning">Connection may be slow</span>
        </div>
      )}
      {connHealthStatus === "down" && activeConnection && (
        <div className="flex items-center justify-between px-6 py-1.5 bg-error/10 border-b border-error/20">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-error shrink-0" />
            <span className="text-xs text-error">Connection is down. Attempting reconnect...</span>
          </div>
          <button
            disabled={reconnecting}
            onClick={() => {
              setReconnecting(true);
              api.connections.reconnect(activeConnection.id).then((r) => {
                if (r.health) setConnHealthStatus(r.health.status);
              }).catch((err) => toast(err instanceof Error ? err.message : "Reconnect failed", "error"))
                .finally(() => setReconnecting(false));
            }}
            className="text-[10px] text-error hover:text-error/80 underline disabled:opacity-50"
          >
            {reconnecting ? "Retrying..." : "Retry"}
          </button>
        </div>
      )}
      <div className="flex-1 overflow-x-hidden overflow-y-auto p-6 space-y-4 chat-scroll" aria-live="polite" aria-relevant="additions" aria-atomic="false">
        {messages.length === 0 ? (
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
        ) : null}
        {messages.map((msg, idx) => {
          const canRetry =
            msg.responseType === "error" &&
            msg.isRetryable !== false &&
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
              onSendMessage={handleSend}
              sessionId={activeSession?.id ?? undefined}
            />
          );
        })}
        {/* Pipeline stage progress (visible even after thinking finishes for checkpoints) */}
        {pipelineStages.length > 0 && (
          <div className="bg-zinc-800/80 rounded-xl px-4 py-3 overflow-hidden">
            <StageProgress
              stages={pipelineStages}
              pipelineRunId={pipelineRunId}
              checkpointStageId={checkpointStageId}
              onContinue={
                checkpointStageId ? () => sendPipelineAction("continue") : undefined
              }
              onModify={
                checkpointStageId || pipelineStages.some((s) => s.status === "failed")
                  ? (mod) => sendPipelineAction("modify", mod)
                  : undefined
              }
              onRetry={
                pipelineStages.some((s) => s.status === "failed")
                  ? () => sendPipelineAction("retry")
                  : undefined
              }
            />
          </div>
        )}
        {isThinking && (
          <div className="flex gap-3">
            {streamingText ? (
              <div className="bg-zinc-800 rounded-xl px-4 py-3 max-w-[95%] md:max-w-[80%] overflow-hidden min-w-0">
                <p className="text-zinc-200 text-sm whitespace-pre-wrap break-words">{streamingText}<span className="inline-block w-1.5 h-4 bg-blue-400 ml-0.5 animate-pulse align-text-bottom" /></p>
                <button
                  onClick={handleStop}
                  className="mt-2 text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors"
                  aria-label="Stop generating"
                >
                  ■ Stop generating
                </button>
              </div>
            ) : (
              <div className="bg-zinc-800 rounded-xl px-4 py-3 space-y-2 max-w-[95%] md:max-w-[80%] overflow-hidden">
                {thinkingLog.length > 0 ? (
                  <ThinkingLog entries={thinkingLog} startTime={thinkingStartTime} />
                ) : (
                  <div className="flex gap-1">
                    <span className="w-2 h-2 bg-zinc-500 rounded-full animate-bounce" />
                    <span className="w-2 h-2 bg-zinc-500 rounded-full animate-bounce [animation-delay:0.1s]" />
                    <span className="w-2 h-2 bg-zinc-500 rounded-full animate-bounce [animation-delay:0.2s]" />
                  </div>
                )}
                {activeToolCalls.length > 0 && (
                  <ToolCallIndicator events={activeToolCalls} />
                )}
                <button
                  onClick={handleStop}
                  className="text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors"
                  aria-label="Stop generating"
                >
                  ■ Stop generating
                </button>
              </div>
            )}
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      {messages.length === 0 && (suggestions.length > 0 || suggestionsLoading) && (
        <SuggestionChips
          suggestions={suggestions}
          loading={suggestionsLoading}
          onSelect={handleSend}
        />
      )}
      <ChatInput onSend={handleSend} disabled={isThinking} />
      {activeConnection && (
        <div className="px-6 pb-2 flex flex-col gap-1 max-w-2xl mx-auto w-full">
          <div className="flex items-center gap-3">
            <CostEstimator projectId={activeProject.id} connectionId={activeConnection.id} onEstimate={handleEstimate} />
            {sessionTokens > 0 && (
              <span className="text-[11px] text-zinc-600 ml-auto">
                Session: {sessionTokens >= 1000 ? `${(sessionTokens / 1000).toFixed(1)}k` : sessionTokens} tokens
                {sessionCost > 0 && (
                  <> / ${sessionCost < 0.01 ? sessionCost.toFixed(4) : sessionCost.toFixed(2)}</>
                )}
              </span>
            )}
          </div>
          {costEstimate && (
            <ContextBudgetIndicator breakdown={costEstimate.breakdown} />
          )}
        </div>
      )}
    </div>
  );
}
