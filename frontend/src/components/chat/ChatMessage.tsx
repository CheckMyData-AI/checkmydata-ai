"use client";

import { useState, useCallback, useEffect } from "react";
import dynamic from "next/dynamic";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const ReactMarkdown = dynamic(() => import("react-markdown"), {
  loading: () => <span className="text-sm text-text-tertiary">Loading…</span>,
});
import type { ChatMessage as ChatMessageType } from "@/stores/app-store";
import { useAppStore } from "@/stores/app-store";
import { VizRenderer } from "@/components/viz/VizRenderer";
import { VizToolbar } from "@/components/viz/VizToolbar";
import { DataTable } from "@/components/viz/DataTable";
import { rerenderViz, type VizTypeKey } from "@/lib/viz-utils";
import { api } from "@/lib/api";
import { toast } from "@/stores/toast-store";
import { useNotesStore } from "@/stores/notes-store";
import { Icon } from "@/components/ui/Icon";
import { ClarificationCard } from "./ClarificationCard";
import { InsightCards, type Insight } from "./InsightCards";
import { SessionContinuationBanner } from "./SessionContinuationBanner";
import { SQLExplainer } from "./SQLExplainer";
import { SQLResultSection } from "./SQLResultSection";
import { VerificationBadge } from "./VerificationBadge";

export const remarkPlugins = [remarkGfm];

export const mdComponents: Components = {
  p: ({ children }) => <p className="text-sm mb-2 last:mb-0">{children}</p>,
  h1: ({ children }) => <h1 className="text-lg font-semibold mb-2 mt-3 first:mt-0 break-words">{children}</h1>,
  h2: ({ children }) => <h2 className="text-base font-semibold mb-2 mt-3 first:mt-0 break-words">{children}</h2>,
  h3: ({ children }) => <h3 className="text-sm font-semibold mb-1.5 mt-2.5 first:mt-0 break-words">{children}</h3>,
  h4: ({ children }) => <h4 className="text-sm font-medium mb-1 mt-2 first:mt-0 break-words">{children}</h4>,
  ul: ({ children }) => <ul className="list-disc pl-4 mb-2 last:mb-0 space-y-0.5 text-sm">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-4 mb-2 last:mb-0 space-y-0.5 text-sm">{children}</ol>,
  li: ({ children }) => <li className="text-sm">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  a: ({ href, children }) => {
    const safeHref = href && /^https?:\/\//i.test(href) ? href : undefined;
    return (
      <a href={safeHref} target="_blank" rel="noopener noreferrer" className="text-accent underline hover:text-accent-hover break-all">
        {children}
      </a>
    );
  },
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-border-default pl-3 my-2 text-text-secondary italic overflow-hidden break-words">{children}</blockquote>
  ),
  code: ({ className, children }) => {
    const isBlock = className?.includes("language-");
    if (isBlock) {
      return <code className="text-xs font-mono">{children}</code>;
    }
    return <code className="bg-surface-1 text-text-primary px-1 py-0.5 rounded text-xs font-mono break-all">{children}</code>;
  },
  pre: ({ children }) => (
    <pre className="bg-surface-1 p-3 rounded-lg overflow-x-auto max-w-full mb-2 last:mb-0">{children}</pre>
  ),
  table: ({ children }) => (
    <div className="overflow-x-auto mb-2 last:mb-0">
      <table className="text-xs border-collapse w-full">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="border-b border-border-default">{children}</thead>,
  th: ({ children }) => <th className="text-left px-2 py-1 text-text-secondary font-medium">{children}</th>,
  td: ({ children }) => <td className="px-2 py-1 border-t border-border-subtle">{children}</td>,
  hr: () => <hr className="border-border-default my-3" />,
  img: () => null,
};

interface AttemptInfo {
  attempt: number;
  query: string;
  explanation?: string;
  error?: string | null;
  error_type?: string | null;
  elapsed_ms?: number;
}

interface RAGSourceInfo {
  source_path: string;
  distance?: number | null;
  doc_type?: string;
}

interface MessageMetadata {
  query?: string;
  viz_type?: string;
  error?: string;
  workflow_id?: string;
  row_count?: number;
  execution_time_ms?: number;
  attempts?: AttemptInfo[];
  total_attempts?: number;
  rag_sources?: RAGSourceInfo[];
  response_type?: string;
  token_usage?: Record<string, number | string | null>;
  insights?: Insight[];
  suggested_followups?: string[];
}

interface ChatMessageProps {
  message: ChatMessageType;
  metadataJson?: string | null;
  onRetry?: () => void;
  onSendMessage?: (text: string) => void;
  onContinueAnalysis?: (continuationContext: string | null) => void;
  sessionId?: string;
}

function resolveOriginalVizType(
  visualization: Record<string, unknown> | null | undefined,
  metaVizType?: string,
): VizTypeKey {
  if (metaVizType === "bar_chart" || metaVizType === "line_chart" || metaVizType === "pie_chart" || metaVizType === "scatter") {
    return metaVizType;
  }
  const vizDataType = visualization?.type as string | undefined;
  if (vizDataType === "chart") {
    const chartType = (visualization?.data as Record<string, unknown>)?.type as string | undefined;
    if (chartType === "bar") return "bar_chart";
    if (chartType === "line") return "line_chart";
    if (chartType === "pie") return "pie_chart";
    if (chartType === "scatter") return "scatter";
  }
  return "table";
}

function computeSqlComplexity(sql: string): string {
  const upper = sql.toUpperCase();
  const hasRecursive = /\bWITH\s+RECURSIVE\b/.test(upper);
  const hasCte = /\bWITH\b\s+\w+\s+AS\s*\(/.test(upper);
  const hasWindow = /\bOVER\s*\(/.test(upper);
  const joinCount = (upper.match(/\bJOIN\b/g) || []).length;
  const fromIdx = upper.indexOf("FROM");
  const hasSubquery = fromIdx >= 0 && upper.indexOf("SELECT", fromIdx + 1) >= 0;

  if (hasRecursive) return "expert";
  if (hasCte && (hasWindow || joinCount > 2)) return "expert";
  if (hasCte || hasWindow || hasSubquery || joinCount > 2) return "complex";
  if (joinCount >= 1) return "moderate";
  return "simple";
}

const complexityBadgeColors: Record<string, string> = {
  simple: "bg-success-muted text-success",
  moderate: "bg-accent-muted text-accent",
  complex: "bg-warning-muted text-warning",
  expert: "bg-error-muted text-error",
};

export function ChatMessage({ message, metadataJson, onRetry, onSendMessage, onContinueAnalysis, sessionId }: ChatMessageProps) {
  const isUser = message.role === "user";
  const [showDetails, setShowDetails] = useState(false);
  const [showSources, setShowSources] = useState(false);
  const [userRating, setUserRating] = useState<number | null>(message.userRating ?? null);
  const [feedbackLoading, setFeedbackLoading] = useState(false);
  const [mobileVizExpanded, setMobileVizExpanded] = useState(false);

  useEffect(() => {
    setUserRating(message.userRating ?? null);
  }, [message.userRating]);

  let metadata: MessageMetadata | null = null;
  if (metadataJson) {
    try {
      metadata = JSON.parse(metadataJson);
    } catch {
      metadata = null;
    }
  }

  const responseType = message.responseType || metadata?.response_type || "text";
  const isSqlResult = responseType === "sql_result";
  const isClarification = responseType === "clarification_request";
  const hasViz = !!message.visualization;
  const hasRawResult = !!message.rawResult;

  const originalVizType = resolveOriginalVizType(message.visualization, metadata?.viz_type);
  const [activeVizType, setActiveVizType] = useState<VizTypeKey>(originalVizType);
  const [overrideViz, setOverrideViz] = useState<Record<string, unknown> | null>(null);
  const [vizLoading, setVizLoading] = useState(false);
  const [viewMode, setViewMode] = useState<"viz" | "text">(hasViz ? "viz" : "text");

  const handleVizTypeChange = useCallback(
    async (newType: VizTypeKey) => {
      if (newType === activeVizType || !message.rawResult) return;
      const previousType = activeVizType;
      setActiveVizType(newType);

      if (newType === originalVizType) {
        setOverrideViz(null);
        return;
      }

      setVizLoading(true);
      try {
        const newViz = await rerenderViz(message.rawResult, newType);
        setOverrideViz(newViz);
      } catch (err) {
        toast(err instanceof Error ? err.message : "Failed to re-render visualization", "error");
        setActiveVizType(previousType);
      } finally {
        setVizLoading(false);
      }
    },
    [activeVizType, originalVizType, message.rawResult],
  );

  const [noteSaving, setNoteSaving] = useState(false);
  const noteSavedFromStore = useNotesStore((s) =>
    message.query ? s.notes.some((n) => n.sql_query === message.query) : false,
  );
  const [noteSavedLocal, setNoteSavedLocal] = useState(false);
  const noteSaved = noteSavedFromStore || noteSavedLocal;

  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryText, setSummaryText] = useState<string | null>(null);
  const [summaryOpen, setSummaryOpen] = useState(false);

  if (responseType === "session_continuation") {
    const rotMeta = metadata as { old_session_id?: string; summary_preview?: string; topics?: string[] } | null;
    const msgCount = parseInt(String(message.content).match(/\((\d+)/)?.[1] ?? "0", 10);
    return (
      <SessionContinuationBanner
        messageCount={msgCount}
        summaryPreview={rotMeta?.summary_preview}
        topics={rotMeta?.topics}
      />
    );
  }

  const handleFeedback = async (rating: number) => {
    if (feedbackLoading) return;
    setFeedbackLoading(true);
    try {
      await api.chat.submitFeedback(message.id, rating);
      setUserRating(rating);

      if (isSqlResult && message.query && sessionId) {
        const { activeProject, activeConnection } = useAppStore.getState();
        if (activeProject && activeConnection?.id) {
          api.dataValidation.validateData({
            connection_id: activeConnection.id,
            session_id: sessionId,
            message_id: message.id,
            query: message.query,
            verdict: rating === 1 ? "confirmed" : "rejected",
            project_id: activeProject.id,
          }).catch(() => {});
        }
      }

      if (rating === -1 && isSqlResult && onSendMessage) {
        onSendMessage(
          "I flagged the previous query result as incorrect. Please investigate what might be wrong and suggest a corrected query."
        );
      }
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to submit feedback", "error");
    } finally {
      setFeedbackLoading(false);
    }
  };

  const handleSaveToNotes = async () => {
    if (noteSaving || noteSaved) return;
    const { activeProject, activeConnection } = useAppStore.getState();
    if (!activeProject || !message.query) return;

    setNoteSaving(true);
    try {
      const title = (message.content || "").split("\n")[0].slice(0, 200) || "Saved query";
      const resultJson = message.rawResult ? JSON.stringify(message.rawResult) : null;
      const vizJson = message.visualization
        ? JSON.stringify(message.visualization)
        : null;
      const note = await api.notes.create({
        project_id: activeProject.id,
        connection_id: activeConnection?.id ?? null,
        title,
        sql_query: message.query,
        answer_text: message.content || null,
        visualization_json: vizJson,
        last_result_json: resultJson,
      });
      useNotesStore.getState().addNote(note);
      useNotesStore.getState().setOpen(true);
      setNoteSavedLocal(true);
      toast("Query saved to notes", "info");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to save note", "error");
    } finally {
      setNoteSaving(false);
    }
  };

  const sqlComplexity = message.query && isSqlResult ? computeSqlComplexity(message.query) : null;

  const handleSummarize = async () => {
    if (summaryLoading) return;
    if (summaryText) {
      setSummaryOpen((v) => !v);
      return;
    }
    const { activeProject } = useAppStore.getState();
    if (!activeProject) return;
    setSummaryLoading(true);
    setSummaryOpen(true);
    try {
      const res = await api.chat.summarize(message.id, activeProject.id);
      setSummaryText(res.summary);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to generate summary", "error");
      setSummaryOpen(false);
    } finally {
      setSummaryLoading(false);
    }
  };

  let toolCalls: Array<{ tool?: string; arguments?: Record<string, unknown>; result_preview?: string }> = [];
  if (message.toolCallsJson) {
    try {
      toolCalls = JSON.parse(message.toolCallsJson);
    } catch { /* ignore */ }
  }

  const hasKnowledgeSources =
    metadata?.rag_sources && metadata.rag_sources.length > 0;

  return (
    <div className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[95%] md:max-w-[80%] min-w-0 overflow-hidden rounded-xl px-3 py-2.5 md:px-4 md:py-3 ${
          isUser ? "bg-accent text-white" : "bg-surface-2 text-text-primary"
        }`}
      >
        {message.stalenessWarning && (
          <div className="mb-2 px-2 py-1.5 rounded bg-warning-muted border border-border-default text-warning text-xs">
            {message.stalenessWarning}
          </div>
        )}

        {/* Response type badge for non-text responses */}
        {!isUser && responseType !== "text" && responseType !== "error" && (
          <div className="mb-1.5 flex items-center gap-1.5">
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded ${
                responseType === "sql_result"
                  ? "bg-accent-muted text-accent"
                  : responseType === "clarification_request"
                  ? "bg-warning-muted text-warning"
                  : responseType === "step_limit_reached"
                  ? "bg-warning-muted text-warning"
                  : "bg-accent-muted text-accent"
              }`}
            >
              {responseType === "sql_result"
                ? "SQL Result"
                : responseType === "clarification_request"
                ? "Question"
                : responseType === "step_limit_reached"
                ? "Partial Result"
                : "Knowledge"}
            </span>
            {isSqlResult && message.verificationStatus && (
              <VerificationBadge status={message.verificationStatus} />
            )}
          </div>
        )}

        {isUser ? (
          <p className="text-sm whitespace-pre-wrap break-words">{message.content}</p>
        ) : (
          <div className="chat-markdown overflow-hidden">
            <ReactMarkdown remarkPlugins={remarkPlugins} components={mdComponents}>{message.content}</ReactMarkdown>
          </div>
        )}

        {/* Clarification card for structured questions */}
        {isClarification && message.clarificationData && onSendMessage && (
          <ClarificationCard
            data={message.clarificationData}
            onSubmit={(answer) => onSendMessage(answer)}
          />
        )}

        {/* Compound SQL results (2+ queries) */}
        {isSqlResult && message.sqlResults && message.sqlResults.length >= 2 && (
          <div className="mt-3">
            {message.sqlResults.map((block, idx) => (
              <SQLResultSection
                key={idx}
                block={block}
                index={idx}
                total={message.sqlResults!.length}
                onSendMessage={onSendMessage}
              />
            ))}
          </div>
        )}

        {/* Single SQL result (legacy / 0-1 results) */}
        {isSqlResult && (!message.sqlResults || message.sqlResults.length < 2) && (
          <>
            {message.query && (
              <details className="mt-3 text-xs">
                <summary className="cursor-pointer text-text-secondary hover:text-text-primary flex items-center gap-2">
                  View SQL Query
                  {sqlComplexity && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${complexityBadgeColors[sqlComplexity] || ""}`}>
                      {sqlComplexity.charAt(0).toUpperCase() + sqlComplexity.slice(1)}
                    </span>
                  )}
                </summary>
                <pre className="mt-2 p-3 bg-surface-1 rounded-lg overflow-x-auto max-w-full text-text-primary">
                  {message.query}
                </pre>
                {message.queryExplanation && (
                  <p className="mt-1 text-text-secondary">{message.queryExplanation}</p>
                )}
                <SQLExplainer
                  sql={message.query}
                  projectId={useAppStore.getState().activeProject?.id ?? ""}
                />
              </details>
            )}

            {hasViz && (
              <div className="mt-3 flex items-center gap-2 flex-wrap">
                <div className="flex items-center gap-0.5 p-0.5 bg-surface-1/60 rounded-lg">
                  <button
                    onClick={() => setViewMode("viz")}
                    aria-label="Show visualization"
                    className={`px-2 py-1 rounded-md text-[11px] transition-colors ${
                      viewMode === "viz"
                        ? "bg-surface-3 text-text-primary"
                        : "text-text-secondary hover:text-text-primary"
                    }`}
                  >
                    Visual
                  </button>
                  <button
                    onClick={() => setViewMode("text")}
                    aria-label="Show data as text"
                    className={`px-2 py-1 rounded-md text-[11px] transition-colors ${
                      viewMode === "text"
                        ? "bg-surface-3 text-text-primary"
                        : "text-text-secondary hover:text-text-primary"
                    }`}
                  >
                    Text
                  </button>
                </div>
                {viewMode === "viz" && hasRawResult && (
                  <VizToolbar
                    activeType={activeVizType}
                    onTypeChange={handleVizTypeChange}
                    loading={vizLoading}
                  />
                )}
              </div>
            )}

            {hasViz && viewMode === "viz" && (
              <div className="mt-2">
                <div className="md:hidden">
                  {mobileVizExpanded ? (
                    <>
                      <VizRenderer data={overrideViz ?? message.visualization!} />
                      <button
                        onClick={() => setMobileVizExpanded(false)}
                        className="mt-1.5 text-[10px] text-text-secondary hover:text-text-primary transition-colors"
                      >
                        Collapse chart
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => setMobileVizExpanded(true)}
                      className="w-full py-3 min-h-[44px] text-xs text-text-secondary hover:text-text-primary bg-surface-1/40 rounded-lg border border-border-default/30 transition-colors text-center"
                    >
                      Tap to view chart
                    </button>
                  )}
                </div>
                <div className="hidden md:block">
                  <VizRenderer data={overrideViz ?? message.visualization!} />
                </div>
              </div>
            )}

            {hasViz && viewMode === "text" && hasRawResult && (
              <div className="mt-2">
                <DataTable
                  data={{
                    columns: message.rawResult!.columns,
                    rows: message.rawResult!.rows.map((row) =>
                      Object.fromEntries(
                        message.rawResult!.columns.map((col, i) => [col, row[i]]),
                      ),
                    ),
                    total_rows: message.rawResult!.total_rows,
                  }}
                />
              </div>
            )}

            {metadata?.insights && metadata.insights.length > 0 && (
              <InsightCards insights={metadata.insights} onDrillDown={onSendMessage} />
            )}
          </>
        )}

        {/* Executive summary button + inline summary */}
        {isSqlResult && message.query && (
          <div className="mt-1.5">
            {!summaryText && (
              <button
                onClick={handleSummarize}
                disabled={summaryLoading}
                className="text-[10px] px-2 py-0.5 rounded border border-border-default text-text-secondary hover:text-text-primary hover:border-border-default transition-colors disabled:opacity-50"
              >
                {summaryLoading ? "Generating..." : "Summary"}
              </button>
            )}
            {summaryText && (
              <div className="mt-1 p-2 rounded-lg bg-surface-1/60 border border-border-subtle text-[11px] text-text-primary leading-relaxed">
                {summaryText}
              </div>
            )}
          </div>
        )}

        {/* Knowledge sources — prominent for knowledge responses */}
        {!isUser && hasKnowledgeSources && responseType === "knowledge" && (
          <div className="mt-3 border-t border-border-default/50 pt-2">
            <button
              onClick={() => setShowSources((v) => !v)}
              className="text-xs text-accent hover:text-accent-hover flex items-center gap-1"
              aria-expanded={showSources}
              aria-label={`${showSources ? "Hide" : "Show"} knowledge sources`}
            >
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
              </svg>
              {showSources ? "Hide" : "Show"} {metadata?.rag_sources?.length ?? 0} source{(metadata?.rag_sources?.length ?? 0) !== 1 ? "s" : ""}
            </button>
            {showSources && (
              <div className="mt-2 space-y-1" role="region" aria-label="Knowledge sources">
                {(metadata?.rag_sources ?? []).map((src, idx) => (
                  <div
                    key={idx}
                    className="flex items-center gap-1.5 py-1 px-2 rounded bg-surface-1/50 text-[11px] text-text-secondary"
                  >
                    <span className="text-[10px] uppercase px-1 py-px rounded bg-accent-muted text-accent">
                      {src.doc_type || "doc"}
                    </span>
                    <span className="truncate flex-1" title={src.source_path}>
                      {src.source_path}
                    </span>
                    {src.distance != null && (
                      <span className="ml-auto text-text-muted tabular-nums">
                        {(1 - src.distance).toFixed(2)}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {message.error && (
          <div className="mt-2 flex items-center gap-2">
            <p className="text-xs text-error">Error: {message.error}</p>
            {onRetry && responseType === "error" && (
              <button
                onClick={onRetry}
                className="text-[10px] px-2 py-0.5 rounded bg-surface-3 text-text-primary hover:bg-surface-3 transition-colors"
              >
                Retry
              </button>
            )}
          </div>
        )}

        {responseType === "step_limit_reached" && onContinueAnalysis && (
          <div className="mt-3 p-3 rounded-lg bg-warning-muted/50 border border-warning/20">
            <div className="flex items-center gap-2 mb-2">
              <svg className="w-4 h-4 text-warning shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <p className="text-xs text-warning font-medium">
                Analysis reached step limit
                {message.stepsUsed && message.stepsTotal
                  ? ` (${message.stepsUsed}/${message.stepsTotal} steps used)`
                  : ""}
              </p>
            </div>
            <p className="text-xs text-text-secondary mb-2">
              The analysis was cut short. Click below to continue from where it left off.
            </p>
            <button
              onClick={() => onContinueAnalysis(message.continuationContext ?? null)}
              className="text-xs px-3 py-1.5 rounded-md bg-accent text-white font-medium hover:bg-accent-hover transition-colors"
            >
              Continue analysis
            </button>
          </div>
        )}

        {/* Thumbs up/down feedback + save to notes */}
        {!isUser && (
          <div className="mt-2 flex items-center gap-1">
            <button
              onClick={() => handleFeedback(1)}
              aria-label="Helpful"
              aria-pressed={userRating === 1}
              disabled={feedbackLoading}
              className={`p-1 rounded transition-colors disabled:opacity-50 ${
                userRating === 1
                  ? "text-success bg-success-muted"
                  : "text-text-tertiary hover:text-text-primary hover:bg-surface-2"
              }`}
              title="Helpful"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.28a2 2 0 002-1.7l1.38-9a2 2 0 00-2-2.3H14z" />
              </svg>
            </button>
            <button
              onClick={() => handleFeedback(-1)}
              aria-label="Not helpful"
              aria-pressed={userRating === -1}
              disabled={feedbackLoading}
              className={`p-1 rounded transition-colors disabled:opacity-50 ${
                userRating === -1
                  ? "text-error bg-error-muted"
                  : "text-text-tertiary hover:text-text-primary hover:bg-surface-2"
              }`}
              title="Not helpful"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M10 15v4a3 3 0 003 3l4-9V2H5.72a2 2 0 00-2 1.7l-1.38 9a2 2 0 002 2.3H10z" />
              </svg>
            </button>
            {isSqlResult && message.query && (
              <>
                <button
                  onClick={handleSaveToNotes}
                  aria-label="Save to notes"
                  disabled={noteSaving || noteSaved}
                  className={`p-1 rounded transition-colors disabled:opacity-50 ml-1 ${
                    noteSaved
                      ? "text-accent bg-accent-muted"
                      : "text-text-tertiary hover:text-text-primary hover:bg-surface-2"
                  }`}
                  title={noteSaved ? "Saved to notes" : "Save to notes"}
                >
                  <Icon name="bookmark" size={14} className={noteSaving ? "animate-pulse" : ""} />
                </button>
                <button
                  onClick={handleSummarize}
                  aria-label="Generate summary"
                  disabled={summaryLoading}
                  className={`p-1 rounded transition-colors disabled:opacity-50 ml-0.5 ${
                    summaryText
                      ? "text-info bg-info-muted"
                      : "text-text-tertiary hover:text-text-primary hover:bg-surface-2"
                  }`}
                  title="Executive summary"
                >
                  <svg className={`w-3.5 h-3.5 ${summaryLoading ? "animate-pulse" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                </button>
              </>
            )}
          </div>
        )}

        {/* Executive summary */}
        {summaryOpen && isSqlResult && (
          <div className="mt-2 p-3 bg-info-muted border border-border-default rounded-lg text-xs">
            {summaryLoading ? (
              <div className="flex items-center gap-2 text-text-secondary">
                <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Generating summary...
              </div>
            ) : summaryText ? (
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] font-medium text-info">Executive Summary</span>
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(summaryText).then(
                        () => toast("Copied to clipboard", "info"),
                        () => toast("Failed to copy", "error"),
                      );
                    }}
                    className="text-[10px] text-text-tertiary hover:text-text-primary transition-colors"
                  >
                    Copy
                  </button>
                </div>
                <p className="text-text-primary leading-relaxed">{summaryText}</p>
              </div>
            ) : null}
          </div>
        )}

        {/* Metadata badges */}
        {!isUser && metadata && (metadata.row_count != null || metadata.execution_time_ms != null || (metadata.total_attempts && metadata.total_attempts > 0) || metadata.token_usage) && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {metadata.execution_time_ms != null && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-3/50 text-text-secondary">
                {metadata.execution_time_ms < 1000
                  ? `${Math.round(metadata.execution_time_ms)}ms`
                  : `${(metadata.execution_time_ms / 1000).toFixed(1)}s`}
              </span>
            )}
            {metadata.row_count != null && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-3/50 text-text-secondary">
                {metadata.row_count} row{metadata.row_count !== 1 ? "s" : ""}
              </span>
            )}
            {metadata.viz_type && metadata.viz_type !== "text" && (
              <span className="hidden md:inline text-[10px] px-1.5 py-0.5 rounded bg-surface-3/50 text-text-secondary">
                {metadata.viz_type}
              </span>
            )}
            {metadata.total_attempts != null && metadata.total_attempts > 1 && (
              <span className={`hidden md:inline text-[10px] px-1.5 py-0.5 rounded ${metadata.error ? "bg-error-muted text-error" : "bg-success-muted text-success"}`}>
                {metadata.error
                  ? `Failed after ${metadata.total_attempts} attempts`
                  : `Resolved after ${metadata.total_attempts} attempts`}
              </span>
            )}
            {metadata.token_usage?.total_tokens != null && Number(metadata.token_usage.total_tokens) > 0 && (
              <span className="hidden md:inline text-[10px] px-1.5 py-0.5 rounded bg-surface-3/50 text-text-secondary" title={`Prompt: ${Number(metadata.token_usage.prompt_tokens ?? 0).toLocaleString()} | Completion: ${Number(metadata.token_usage.completion_tokens ?? 0).toLocaleString()}`}>
                {Number(metadata.token_usage.prompt_tokens ?? 0).toLocaleString()} in / {Number(metadata.token_usage.completion_tokens ?? 0).toLocaleString()} out
              </span>
            )}
            {metadata.token_usage?.estimated_cost_usd != null && Number(metadata.token_usage.estimated_cost_usd) > 0 && (
              <span className="hidden md:inline text-[10px] px-1.5 py-0.5 rounded bg-info-muted text-info">
                ${Number(metadata.token_usage.estimated_cost_usd) < 0.01
                  ? Number(metadata.token_usage.estimated_cost_usd).toFixed(4)
                  : Number(metadata.token_usage.estimated_cost_usd).toFixed(2)}
              </span>
            )}
            <button
              onClick={() => setShowDetails((v) => !v)}
              className="text-[10px] text-text-tertiary hover:text-text-primary ml-1"
              aria-expanded={showDetails}
              aria-label={showDetails ? "Hide message details" : "Show message details"}
            >
              {showDetails ? "hide details" : "details"}
            </button>
          </div>
        )}

        {/* Expandable details */}
        {showDetails && metadata && (
          <div className="mt-2 p-2 bg-surface-1/50 rounded text-[10px] text-text-tertiary space-y-1">
            {metadata.workflow_id && <div>Workflow: {metadata.workflow_id}</div>}
            {metadata.response_type && <div>Response type: {metadata.response_type}</div>}
            {metadata.execution_time_ms != null && (
              <div>Execution: {metadata.execution_time_ms.toFixed(1)}ms</div>
            )}
            {metadata.row_count != null && <div>Rows: {metadata.row_count}</div>}
            {metadata.viz_type && <div>Visualization: {metadata.viz_type}</div>}
            {metadata.error && <div className="text-error">Error: {metadata.error}</div>}

            {metadata.token_usage?.total_tokens != null && Number(metadata.token_usage.total_tokens) > 0 && (
              <div className="mt-1.5 border-t border-border-subtle pt-1.5">
                <div className="font-medium text-text-secondary mb-1">Token Usage</div>
                <div>Prompt: {Number(metadata.token_usage.prompt_tokens ?? 0).toLocaleString()}</div>
                <div>Completion: {Number(metadata.token_usage.completion_tokens ?? 0).toLocaleString()}</div>
                <div>Total: {Number(metadata.token_usage.total_tokens).toLocaleString()}</div>
                {metadata.token_usage.provider && (
                  <div>Provider: {String(metadata.token_usage.provider)}</div>
                )}
                {metadata.token_usage.model && (
                  <div>Model: {String(metadata.token_usage.model)}</div>
                )}
                {metadata.token_usage.estimated_cost_usd != null && Number(metadata.token_usage.estimated_cost_usd) > 0 && (
                  <div>Cost: ${Number(metadata.token_usage.estimated_cost_usd).toFixed(4)}</div>
                )}
              </div>
            )}

            {metadata.rag_sources && metadata.rag_sources.length > 0 && responseType !== "knowledge" && (
              <div className="mt-1.5 border-t border-border-subtle pt-1.5">
                <div className="font-medium text-text-secondary mb-1">
                  Code Context ({metadata.rag_sources.length} sources)
                </div>
                {metadata.rag_sources.map((src, idx) => (
                  <div
                    key={idx}
                    className="flex items-center gap-1.5 py-0.5 text-text-tertiary"
                  >
                    <span className="text-[10px] uppercase px-1 py-px rounded bg-surface-2 text-text-tertiary">
                      {src.doc_type || "doc"}
                    </span>
                    <span className="truncate flex-1" title={src.source_path}>
                      {src.source_path?.split("/").pop() || src.source_path}
                    </span>
                    {src.distance != null && (
                      <span className="ml-auto text-text-muted tabular-nums">
                        {(1 - src.distance).toFixed(2)} sim
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}

            {metadata.attempts && metadata.attempts.length > 0 && (
              <div className="mt-1.5 border-t border-border-subtle pt-1.5">
                <div className="font-medium text-text-secondary mb-1">
                  Attempt History ({metadata.attempts.length})
                </div>
                {metadata.attempts.map((att) => (
                  <div
                    key={att.attempt}
                    className={`p-1.5 rounded mb-1 ${
                      att.error
                        ? "bg-error-muted border border-border-default"
                        : "bg-success-muted border border-border-default"
                    }`}
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="font-medium">#{att.attempt}</span>
                      {att.error ? (
                        <span className="text-error">{att.error_type}: {att.error}</span>
                      ) : (
                        <span className="text-success">Success</span>
                      )}
                      {att.elapsed_ms != null && (
                        <span className="ml-auto text-text-muted">
                          {att.elapsed_ms < 1000
                            ? `${Math.round(att.elapsed_ms)}ms`
                            : `${(att.elapsed_ms / 1000).toFixed(1)}s`}
                        </span>
                      )}
                    </div>
                    <pre className="mt-0.5 text-text-muted truncate max-w-full overflow-hidden">
                      {att.query?.slice(0, 200)}
                    </pre>
                  </div>
                ))}
              </div>
            )}

            {toolCalls.length > 0 && (
              <div className="mt-1.5 border-t border-border-subtle pt-1.5">
                <div className="font-medium text-text-secondary mb-1">
                  Tool Calls ({toolCalls.length})
                </div>
                {toolCalls.map((tc: { tool?: string; arguments?: Record<string, unknown>; result_preview?: string }, idx: number) => (
                  <div
                    key={idx}
                    className="p-1.5 rounded mb-1 bg-info-muted border border-border-default"
                  >
                    <span className="text-info font-medium">{tc.tool}</span>
                    {tc.arguments && (
                      <pre className="mt-0.5 text-text-muted truncate max-w-full overflow-hidden">
                        {JSON.stringify(tc.arguments).slice(0, 150)}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
