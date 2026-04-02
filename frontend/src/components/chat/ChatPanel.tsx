"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { useAppStore } from "@/stores/app-store";
import { api, type ChatResponse, type StreamError, type QuerySuggestion, type CostEstimate } from "@/lib/api";
import type { WorkflowEvent } from "@/lib/sse";
import { toast } from "@/stores/toast-store";
import dynamic from "next/dynamic";
import { ChatInput } from "./ChatInput";
import { ChatMessage, mdComponents, remarkPlugins } from "./ChatMessage";

const ReactMarkdown = dynamic(() => import("react-markdown"), {
  loading: () => <span className="text-sm text-text-tertiary">Loading…</span>,
});
import { SuggestionChips } from "./SuggestionChips";
import { ThinkingLog } from "./ThinkingLog";
import { StageProgress, type PipelineStage } from "./StageProgress";
import { ReadinessGate, ReadinessBanner } from "./ReadinessGate";
import { ConnectionHealth } from "@/components/connections/ConnectionHealth";
import { CostEstimator } from "./CostEstimator";
import { ContextBudgetIndicator } from "./ContextBudgetIndicator";
import { useSessionPolling } from "@/hooks/useSessionPolling";

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

  const isBackgroundProcessing =
    activeSession?.status === "processing" && !isThinking;

  useSessionPolling();

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
      abortRef.current?.abort();
      setCheckpointStageId(undefined);
      setThinking(true);
      setLoading(true);
      setThinkingLog([]);
      setStreamingText("");

      const ctrl = api.chat.askStream(
        {
          project_id: activeProject.id,
          connection_id: activeSession.connection_id ?? activeConnection?.id,
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

  const handleContinueAnalysis = useCallback(
    (continuationContext: string | null) => {
      if (!activeProject || !activeSession) return;
      abortRef.current?.abort();
      const currentMessages = useAppStore.getState().messages;
      const lastUserMsg = [...currentMessages].reverse().find((m) => m.role === "user");
      const message = lastUserMsg?.content ?? "Continue the analysis";

      addMessage({
        id: crypto.randomUUID(),
        role: "user" as const,
        content: "Continue analysis",
        timestamp: Date.now(),
      });
      setThinking(true);
      setLoading(true);
      setThinkingLog([]);
      setStreamingText("");

      const extra: Record<string, unknown> = {
        pipeline_action: "continue_analysis",
      };
      if (continuationContext) {
        extra.continuation_context = continuationContext;
      }

      const ctrl = api.chat.askStream(
        {
          project_id: activeProject.id,
          connection_id: activeSession.connection_id ?? activeConnection?.id,
          message,
          session_id: activeSession.id,
          pipeline_action: "continue_analysis",
          ...extra,
        },
        (step) => setStreamSteps((prev) => {
          const next = [...prev, step as unknown as WorkflowEvent];
          return next.length > 100 ? next.slice(-100) : next;
        }),
        (result: ChatResponse) => {
          const contSqlResults = result.sql_results?.map((sr) => ({
            query: sr.query ?? undefined,
            queryExplanation: sr.query_explanation ?? undefined,
            visualization: sr.visualization ?? undefined,
            rawResult: sr.raw_result ?? undefined,
            insights: sr.insights ?? undefined,
          })) ?? undefined;

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
            stepsUsed: result.steps_used ?? undefined,
            stepsTotal: result.steps_total ?? undefined,
            continuationContext: result.continuation_context ?? undefined,
            sqlResults: contSqlResults,
          });
          setThinking(false);
          setLoading(false);
          setStreamSteps([]);
          clearToolCalls();
          setThinkingLog([]);
          setStreamingText("");
        },
        (streamErr: StreamError) => {
          addMessage({
            id: crypto.randomUUID(),
            role: "assistant",
            content: streamErr.error || "An error occurred.",
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
    [activeProject, activeConnection, activeSession, addMessage, setThinking, setLoading, clearToolCalls, addToolCall, handlePipelineEvent, handleThinkingEvent, handleToken],
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
  }, [activeProject?.id, activeConnection?.id]);

  useEffect(() => {
    resetSessionUsage();
  }, [activeSession?.id, resetSessionUsage]);

  const prevSessionRef = useRef<string | undefined>(activeSession?.id);
  useEffect(() => {
    const prevId = prevSessionRef.current;
    const newId = activeSession?.id;
    prevSessionRef.current = newId;
    if (prevId && prevId !== newId) {
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
      if (isThinking) {
        setThinking(false);
        setLoading(false);
        clearToolCalls();
        setThinkingLog([]);
        setPipelineStages([]);
        setPipelineRunId(undefined);
        setCheckpointStageId(undefined);
        setStreamSteps([]);
        setStreamingText((prev) => {
          if (prev) {
            useAppStore.getState().addSessionMessage(prevId, {
              id: crypto.randomUUID(),
              role: "assistant",
              content: prev + "\n\n*(Generation stopped — switched session)*",
              timestamp: Date.now(),
            });
          }
          return "";
        });
      }
    }
  }, [activeSession?.id, isThinking, setThinking, setLoading, clearToolCalls]);

  const canChat = activeProject && (activeConnection || chatMode === "knowledge_only");

  const handleSend = useCallback(
    async (content: string) => {
      if (!activeProject) return;

      let currentSession = activeSession;
      const isFirstMessage = messages.length === 0;

      if (!currentSession) {
        try {
          const created = await api.chat.createSession({
            project_id: activeProject.id,
            connection_id: activeConnection?.id ?? undefined,
          });
          currentSession = {
            id: created.id,
            project_id: created.project_id,
            title: created.title,
            connection_id: created.connection_id ?? null,
          };
          setActiveSession(currentSession);
          useAppStore.setState((state) => ({
            chatSessions: [currentSession!, ...state.chatSessions],
          }));
        } catch (err) {
          toast(err instanceof Error ? err.message : "Failed to create chat", "error");
          return;
        }
      }

      const sessionId = currentSession.id;

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
          connection_id: currentSession.connection_id ?? activeConnection?.id,
          message: content,
          session_id: sessionId,
        },
        (step) => {
          setStreamSteps((prev) => {
            const next = [...prev, step as unknown as WorkflowEvent];
            return next.length > 100 ? next.slice(-100) : next;
          });
        },
        (result: ChatResponse) => {
          if (isFirstMessage) {
            api.chat.generateTitle(sessionId).then((updated) => {
              const updatedSession = {
                id: updated.id,
                project_id: updated.project_id,
                title: updated.title,
                connection_id: currentSession!.connection_id ?? null,
              };
              useAppStore.setState((state) => {
                const isCurrent = state.activeSession?.id === updated.id;
                return {
                  ...(isCurrent ? { activeSession: updatedSession } : {}),
                  chatSessions: state.chatSessions.map((s) =>
                    s.id === updated.id ? updatedSession : s,
                  ),
                };
              });
            }).catch(() => { /* keep default title */ });
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

          const apiSqlResults = result.sql_results;
          const sqlResults = apiSqlResults?.map((sr) => ({
            query: sr.query ?? undefined,
            queryExplanation: sr.query_explanation ?? undefined,
            visualization: sr.visualization ?? undefined,
            rawResult: sr.raw_result ?? undefined,
            insights: sr.insights ?? undefined,
          })) ?? undefined;

          if (sqlResults) {
            (metadataObj as Record<string, unknown>).sql_results = apiSqlResults;
          }

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
            stepsUsed: result.steps_used ?? undefined,
            stepsTotal: result.steps_total ?? undefined,
            continuationContext: result.continuation_context ?? undefined,
            sqlResults: sqlResults ?? undefined,
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
        (rotationEvent) => {
          const newSession = {
            id: rotationEvent.new_session_id,
            project_id: activeProject.id,
            title: `Continued session`,
            connection_id: currentSession?.connection_id ?? activeConnection?.id ?? null,
          };
          setActiveSession(newSession);
          useAppStore.setState((state) => ({
            chatSessions: [newSession, ...state.chatSessions],
          }));
          addMessage({
            id: `rotation-${rotationEvent.new_session_id}`,
            role: "system",
            content: `Session continued (${rotationEvent.message_count} earlier messages summarized)`,
            timestamp: Date.now(),
            responseType: "session_continuation",
            metadataJson: JSON.stringify({
              old_session_id: rotationEvent.old_session_id,
              summary_preview: rotationEvent.summary_preview,
              topics: rotationEvent.topics,
            }),
          });
        },
      );
      abortRef.current = ctrl;
    },
    [activeProject, activeConnection, activeSession, messages.length, addMessage, updateMessageId, setThinking, setLoading, setActiveSession, clearToolCalls, addToolCall, bumpRulesVersion, addSessionUsage, handlePipelineEvent, handleThinkingEvent, handleToken],
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
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-text-tertiary">
        <p>No database connection configured.</p>
        <button
          onClick={() => useAppStore.getState().setChatMode("knowledge_only")}
          className="px-4 py-2 bg-accent text-white text-sm rounded-lg hover:bg-accent-hover transition-colors"
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
        <div className="flex items-center justify-between px-6 py-1.5 bg-accent-muted border-b border-border-default">
          <span className="text-xs text-accent">Knowledge Base Mode</span>
          <button
            onClick={() => useAppStore.getState().setChatMode("full")}
            className="text-[10px] text-accent hover:text-accent-hover"
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
            <span className="text-xs text-error">Connection is down. Click Retry to reconnect.</span>
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
          <div className="text-center text-text-tertiary text-sm mt-20">
            <p className="text-lg font-medium mb-2">
              {activeConnection ? "Ready to query" : "Knowledge Base Mode"}
            </p>
            {activeConnection ? (
              <p>
                Connected to{" "}
                <span className="text-text-primary">{activeConnection.name}</span>{" "}
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
              onContinueAnalysis={
                msg.responseType === "step_limit_reached" ? handleContinueAnalysis : undefined
              }
              sessionId={activeSession?.id ?? undefined}
            />
          );
        })}
        {/* Pipeline stage progress (visible even after thinking finishes for checkpoints) */}
        {pipelineStages.length > 0 && (
          <div className="bg-surface-2/80 rounded-xl px-4 py-3 overflow-hidden">
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
              <div className="bg-surface-2 rounded-xl px-4 py-3 max-w-[95%] md:max-w-[80%] overflow-hidden min-w-0">
                <div className="chat-markdown overflow-hidden">
                  <ReactMarkdown remarkPlugins={remarkPlugins} components={mdComponents}>{streamingText}</ReactMarkdown>
                  <span className="inline-block w-1.5 h-4 bg-accent ml-0.5 animate-pulse align-text-bottom" />
                </div>
                <button
                  onClick={handleStop}
                  className="mt-2 text-[10px] text-text-tertiary hover:text-text-primary transition-colors"
                  aria-label="Stop generating"
                >
                  ■ Stop generating
                </button>
              </div>
            ) : (
              <div className="bg-surface-2 rounded-xl px-4 py-3 space-y-2 max-w-[95%] md:max-w-[80%] overflow-hidden">
                {thinkingLog.length > 0 ? (
                  <ThinkingLog entries={thinkingLog} startTime={thinkingStartTime} />
                ) : (
                  <div className="flex gap-1">
                    <span className="w-2 h-2 bg-surface-3 rounded-full animate-bounce" />
                    <span className="w-2 h-2 bg-surface-3 rounded-full animate-bounce [animation-delay:0.1s]" />
                    <span className="w-2 h-2 bg-surface-3 rounded-full animate-bounce [animation-delay:0.2s]" />
                  </div>
                )}
                <button
                  onClick={handleStop}
                  className="text-[10px] text-text-tertiary hover:text-text-primary transition-colors"
                  aria-label="Stop generating"
                >
                  ■ Stop generating
                </button>
              </div>
            )}
          </div>
        )}
        {isBackgroundProcessing && (
          <div className="flex gap-3">
            <div className="bg-surface-2 rounded-xl px-4 py-3 max-w-[95%] md:max-w-[80%] overflow-hidden">
              <div className="flex items-center gap-2">
                <div className="flex gap-1">
                  <span className="w-2 h-2 bg-accent rounded-full animate-bounce" />
                  <span className="w-2 h-2 bg-accent rounded-full animate-bounce [animation-delay:0.1s]" />
                  <span className="w-2 h-2 bg-accent rounded-full animate-bounce [animation-delay:0.2s]" />
                </div>
                <span className="text-sm text-text-secondary">
                  Processing in background&hellip;
                </span>
              </div>
              <p className="text-[11px] text-text-muted mt-1">
                The response is being generated. It will appear here automatically.
              </p>
            </div>
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
              <span className="text-[11px] text-text-muted ml-auto">
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
