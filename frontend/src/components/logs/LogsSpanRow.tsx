"use client";

import { useState } from "react";
import { Icon } from "@/components/ui/Icon";
import type { LogTraceSpan } from "@/lib/api";

const TYPE_CONFIG: Record<string, { icon: Parameters<typeof Icon>[0]["name"]; color: string; label: string }> = {
  llm_call: { icon: "zap", color: "text-info", label: "LLM" },
  db_query: { icon: "database", color: "text-accent", label: "DB" },
  sub_agent: { icon: "layers", color: "text-warning", label: "Agent" },
  viz: { icon: "bar-chart-2", color: "text-success", label: "Viz" },
  rag: { icon: "search", color: "text-info", label: "RAG" },
  validation: { icon: "shield", color: "text-text-muted", label: "Valid" },
  tool_call: { icon: "terminal", color: "text-text-secondary", label: "Tool" },
};

const STATUS_COLORS: Record<string, string> = {
  completed: "text-success",
  failed: "text-error",
  skipped: "text-text-muted",
  started: "text-info",
};

function fmtMs(ms: number | null): string {
  if (ms == null) return "";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

interface Props {
  span: LogTraceSpan;
  depth?: number;
  childSpans?: LogTraceSpan[];
}

export function LogsSpanRow({ span, depth = 0, childSpans }: Props) {
  const [expanded, setExpanded] = useState(false);
  const cfg = TYPE_CONFIG[span.span_type] || TYPE_CONFIG.tool_call;
  const statusColor = STATUS_COLORS[span.status] || "text-text-tertiary";
  const hasChildren = childSpans && childSpans.length > 0;
  const hasDetail =
    span.detail ||
    span.input_preview ||
    span.output_preview ||
    span.token_usage_json;

  const canExpand = hasChildren || hasDetail;

  let tokenInfo: { prompt?: number; completion?: number; total?: number; model?: string } | null = null;
  if (span.token_usage_json) {
    try {
      tokenInfo = JSON.parse(span.token_usage_json);
    } catch { /* ignore */ }
  }

  return (
    <div>
      <button
        onClick={() => canExpand && setExpanded(!expanded)}
        className={`w-full flex items-center gap-2 px-2 py-1.5 text-xs transition-colors rounded-md ${
          canExpand ? "hover:bg-surface-2 cursor-pointer" : "cursor-default"
        } ${span.status === "failed" ? "bg-error/5" : ""}`}
        style={{ paddingLeft: `${8 + depth * 16}px` }}
        aria-expanded={canExpand ? expanded : undefined}
      >
        {canExpand ? (
          <Icon
            name={expanded ? "chevron-down" : "chevron-right"}
            size={10}
            className="text-text-muted shrink-0"
          />
        ) : (
          <span className="w-2.5 shrink-0" />
        )}

        <Icon name={cfg.icon} size={12} className={`${cfg.color} shrink-0`} />

        <span className={`font-mono text-[10px] ${cfg.color} w-10 text-left shrink-0`}>
          {cfg.label}
        </span>

        <span className="text-text-primary truncate text-left flex-1 min-w-0">
          {span.name}
        </span>

        <span className={`shrink-0 text-[10px] ${statusColor}`}>{span.status}</span>

        {fmtMs(span.duration_ms) && (
          <span className="text-[10px] text-text-muted tabular-nums shrink-0 w-14 text-right">
            {fmtMs(span.duration_ms)}
          </span>
        )}

        {tokenInfo && tokenInfo.total ? (
          <span className="text-[10px] text-text-muted tabular-nums shrink-0 w-16 text-right">
            {tokenInfo.total.toLocaleString()} tok
          </span>
        ) : (
          <span className="w-16 shrink-0" />
        )}
      </button>

      {expanded && hasDetail && (
        <div
          className="mx-2 mb-1 rounded-md bg-surface-2/50 border border-border-subtle text-[11px] overflow-hidden"
          style={{ marginLeft: `${24 + depth * 16}px` }}
        >
          {span.detail && span.status === "failed" && (
            <div className="px-3 py-2 border-b border-border-subtle">
              <span className="text-error font-medium">Error: </span>
              <span className="text-error/80">{span.detail}</span>
            </div>
          )}
          {span.input_preview && (
            <div className="px-3 py-2 border-b border-border-subtle">
              <span className="text-text-tertiary font-medium">Input: </span>
              <pre className="text-text-secondary font-mono whitespace-pre-wrap break-all mt-0.5 max-h-32 overflow-y-auto">
                {span.input_preview}
              </pre>
            </div>
          )}
          {span.output_preview && (
            <div className="px-3 py-2 border-b border-border-subtle">
              <span className="text-text-tertiary font-medium">Output: </span>
              <pre className="text-text-secondary font-mono whitespace-pre-wrap break-all mt-0.5 max-h-32 overflow-y-auto">
                {span.output_preview}
              </pre>
            </div>
          )}
          {tokenInfo && (
            <div className="px-3 py-2 flex gap-4 text-text-muted">
              {tokenInfo.model && <span>Model: {tokenInfo.model}</span>}
              {tokenInfo.prompt != null && <span>Prompt: {tokenInfo.prompt.toLocaleString()}</span>}
              {tokenInfo.completion != null && <span>Completion: {tokenInfo.completion.toLocaleString()}</span>}
              {tokenInfo.total != null && <span>Total: {tokenInfo.total.toLocaleString()}</span>}
            </div>
          )}
        </div>
      )}

      {expanded &&
        childSpans?.map((child) => (
          <LogsSpanRow key={child.id} span={child} depth={depth + 1} />
        ))}
    </div>
  );
}
