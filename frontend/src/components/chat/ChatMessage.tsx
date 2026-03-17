"use client";

import { useState } from "react";
import type { ChatMessage as ChatMessageType } from "@/stores/app-store";
import { VizRenderer } from "@/components/viz/VizRenderer";
import { api } from "@/lib/api";
import { toast } from "@/stores/toast-store";

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
  token_usage?: Record<string, number>;
}

interface ChatMessageProps {
  message: ChatMessageType;
  metadataJson?: string | null;
  onRetry?: () => void;
}

export function ChatMessage({ message, metadataJson, onRetry }: ChatMessageProps) {
  const isUser = message.role === "user";
  const [showDetails, setShowDetails] = useState(false);
  const [showSources, setShowSources] = useState(false);
  const [userRating, setUserRating] = useState<number | null>(null);

  const handleFeedback = async (rating: number) => {
    try {
      await api.chat.submitFeedback(message.id, rating);
      setUserRating(rating);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to submit feedback", "error");
    }
  };

  let metadata: MessageMetadata | null = null;
  if (metadataJson) {
    try {
      metadata = JSON.parse(metadataJson);
    } catch {
      metadata = null;
    }
  }

  const responseType = message.responseType || metadata?.response_type || "text";
  const hasKnowledgeSources =
    metadata?.rag_sources && metadata.rag_sources.length > 0;

  return (
    <div className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-xl px-4 py-3 ${
          isUser ? "bg-blue-600 text-white" : "bg-zinc-800 text-zinc-100"
        }`}
      >
        {message.stalenessWarning && (
          <div className="mb-2 px-2 py-1.5 rounded bg-amber-900/20 border border-amber-800/30 text-amber-400 text-xs">
            {message.stalenessWarning}
          </div>
        )}

        {/* Response type badge for non-text responses */}
        {!isUser && responseType !== "text" && responseType !== "error" && (
          <div className="mb-1.5">
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded ${
                responseType === "sql_result"
                  ? "bg-blue-900/30 text-blue-400"
                  : "bg-purple-900/30 text-purple-400"
              }`}
            >
              {responseType === "sql_result" ? "SQL Result" : "Knowledge"}
            </span>
          </div>
        )}

        <p className="text-sm whitespace-pre-wrap">{message.content}</p>

        {/* SQL Query — only for sql_result responses */}
        {message.query && responseType === "sql_result" && (
          <details className="mt-3 text-xs">
            <summary className="cursor-pointer text-zinc-400 hover:text-zinc-300">
              View SQL Query
            </summary>
            <pre className="mt-2 p-3 bg-zinc-900 rounded-lg overflow-x-auto text-zinc-300">
              {message.query}
            </pre>
            {message.queryExplanation && (
              <p className="mt-1 text-zinc-400">{message.queryExplanation}</p>
            )}
          </details>
        )}

        {/* Visualization — only for sql_result responses */}
        {message.visualization && responseType === "sql_result" && (
          <div className="mt-3">
            <VizRenderer data={message.visualization} />
          </div>
        )}

        {/* Knowledge sources — prominent for knowledge responses */}
        {!isUser && hasKnowledgeSources && responseType === "knowledge" && (
          <div className="mt-3 border-t border-zinc-700/50 pt-2">
            <button
              onClick={() => setShowSources((v) => !v)}
              className="text-xs text-purple-400 hover:text-purple-300 flex items-center gap-1"
            >
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
              </svg>
              {showSources ? "Hide" : "Show"} {metadata!.rag_sources!.length} source{metadata!.rag_sources!.length !== 1 ? "s" : ""}
            </button>
            {showSources && (
              <div className="mt-2 space-y-1">
                {metadata!.rag_sources!.map((src, idx) => (
                  <div
                    key={idx}
                    className="flex items-center gap-1.5 py-1 px-2 rounded bg-zinc-900/50 text-[11px] text-zinc-400"
                  >
                    <span className="text-[9px] uppercase px-1 py-px rounded bg-purple-900/30 text-purple-400">
                      {src.doc_type || "doc"}
                    </span>
                    <span className="truncate flex-1">
                      {src.source_path}
                    </span>
                    {src.distance != null && (
                      <span className="ml-auto text-zinc-600 tabular-nums">
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
            <p className="text-xs text-red-400">Error: {message.error}</p>
            {onRetry && responseType === "error" && (
              <button
                onClick={onRetry}
                className="text-[10px] px-2 py-0.5 rounded bg-zinc-700 text-zinc-300 hover:bg-zinc-600 transition-colors"
              >
                Retry
              </button>
            )}
          </div>
        )}

        {/* Thumbs up/down feedback */}
        {!isUser && (
          <div className="mt-2 flex items-center gap-1">
            <button
              onClick={() => handleFeedback(1)}
              className={`p-1 rounded transition-colors ${
                userRating === 1
                  ? "text-emerald-400 bg-emerald-900/30"
                  : "text-zinc-600 hover:text-zinc-400 hover:bg-zinc-800"
              }`}
              title="Helpful"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.28a2 2 0 002-1.7l1.38-9a2 2 0 00-2-2.3H14z" />
              </svg>
            </button>
            <button
              onClick={() => handleFeedback(-1)}
              className={`p-1 rounded transition-colors ${
                userRating === -1
                  ? "text-red-400 bg-red-900/30"
                  : "text-zinc-600 hover:text-zinc-400 hover:bg-zinc-800"
              }`}
              title="Not helpful"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M10 15v4a3 3 0 003 3l4-9V2H5.72a2 2 0 00-2 1.7l-1.38 9a2 2 0 002 2.3H10z" />
              </svg>
            </button>
          </div>
        )}

        {/* Metadata badges */}
        {!isUser && metadata && (metadata.row_count != null || metadata.execution_time_ms != null || (metadata.total_attempts && metadata.total_attempts > 0) || metadata.token_usage) && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {metadata.execution_time_ms != null && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-700/50 text-zinc-400">
                {metadata.execution_time_ms < 1000
                  ? `${Math.round(metadata.execution_time_ms)}ms`
                  : `${(metadata.execution_time_ms / 1000).toFixed(1)}s`}
              </span>
            )}
            {metadata.row_count != null && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-700/50 text-zinc-400">
                {metadata.row_count} row{metadata.row_count !== 1 ? "s" : ""}
              </span>
            )}
            {metadata.viz_type && metadata.viz_type !== "text" && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-700/50 text-zinc-400">
                {metadata.viz_type}
              </span>
            )}
            {metadata.total_attempts != null && metadata.total_attempts > 1 && (
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${metadata.error ? "bg-red-900/30 text-red-400" : "bg-emerald-900/30 text-emerald-400"}`}>
                {metadata.error
                  ? `Failed after ${metadata.total_attempts} attempts`
                  : `Resolved after ${metadata.total_attempts} attempts`}
              </span>
            )}
            {metadata.token_usage?.total_tokens != null && metadata.token_usage.total_tokens > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-700/50 text-zinc-400">
                {metadata.token_usage.total_tokens.toLocaleString()} tokens
              </span>
            )}
            <button
              onClick={() => setShowDetails((v) => !v)}
              className="text-[10px] text-zinc-500 hover:text-zinc-300 ml-1"
            >
              {showDetails ? "hide details" : "details"}
            </button>
          </div>
        )}

        {/* Expandable details */}
        {showDetails && metadata && (
          <div className="mt-2 p-2 bg-zinc-900/50 rounded text-[10px] text-zinc-500 space-y-1">
            {metadata.workflow_id && <div>Workflow: {metadata.workflow_id}</div>}
            {metadata.response_type && <div>Response type: {metadata.response_type}</div>}
            {metadata.execution_time_ms != null && (
              <div>Execution: {metadata.execution_time_ms.toFixed(1)}ms</div>
            )}
            {metadata.row_count != null && <div>Rows: {metadata.row_count}</div>}
            {metadata.viz_type && <div>Visualization: {metadata.viz_type}</div>}
            {metadata.error && <div className="text-red-400">Error: {metadata.error}</div>}

            {metadata.token_usage?.total_tokens != null && metadata.token_usage.total_tokens > 0 && (
              <div className="mt-1.5 border-t border-zinc-800 pt-1.5">
                <div className="font-medium text-zinc-400 mb-1">Token Usage</div>
                <div>Prompt: {metadata.token_usage.prompt_tokens?.toLocaleString() ?? 0}</div>
                <div>Completion: {metadata.token_usage.completion_tokens?.toLocaleString() ?? 0}</div>
                <div>Total: {metadata.token_usage.total_tokens.toLocaleString()}</div>
              </div>
            )}

            {metadata.rag_sources && metadata.rag_sources.length > 0 && responseType !== "knowledge" && (
              <div className="mt-1.5 border-t border-zinc-800 pt-1.5">
                <div className="font-medium text-zinc-400 mb-1">
                  Code Context ({metadata.rag_sources.length} sources)
                </div>
                {metadata.rag_sources.map((src, idx) => (
                  <div
                    key={idx}
                    className="flex items-center gap-1.5 py-0.5 text-zinc-500"
                  >
                    <span className="text-[9px] uppercase px-1 py-px rounded bg-zinc-800 text-zinc-500">
                      {src.doc_type || "doc"}
                    </span>
                    <span className="truncate flex-1">
                      {src.source_path?.split("/").pop() || src.source_path}
                    </span>
                    {src.distance != null && (
                      <span className="ml-auto text-zinc-600 tabular-nums">
                        {(1 - src.distance).toFixed(2)} sim
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}

            {metadata.attempts && metadata.attempts.length > 0 && (
              <div className="mt-1.5 border-t border-zinc-800 pt-1.5">
                <div className="font-medium text-zinc-400 mb-1">
                  Attempt History ({metadata.attempts.length})
                </div>
                {metadata.attempts.map((att) => (
                  <div
                    key={att.attempt}
                    className={`p-1.5 rounded mb-1 ${
                      att.error
                        ? "bg-red-950/30 border border-red-900/30"
                        : "bg-emerald-950/30 border border-emerald-900/30"
                    }`}
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="font-medium">#{att.attempt}</span>
                      {att.error ? (
                        <span className="text-red-400">{att.error_type}: {att.error}</span>
                      ) : (
                        <span className="text-emerald-400">Success</span>
                      )}
                      {att.elapsed_ms != null && (
                        <span className="ml-auto text-zinc-600">
                          {att.elapsed_ms < 1000
                            ? `${Math.round(att.elapsed_ms)}ms`
                            : `${(att.elapsed_ms / 1000).toFixed(1)}s`}
                        </span>
                      )}
                    </div>
                    <pre className="mt-0.5 text-zinc-600 truncate max-w-full overflow-hidden">
                      {att.query?.slice(0, 200)}
                    </pre>
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
