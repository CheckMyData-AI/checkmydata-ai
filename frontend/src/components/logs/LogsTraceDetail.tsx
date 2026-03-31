"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { LogTraceDetail, LogTraceSpan } from "@/lib/api";
import { LogsSpanRow } from "./LogsSpanRow";
import { Icon } from "@/components/ui/Icon";

interface Props {
  projectId: string;
  traceId: string;
  onClose: () => void;
}

function buildSpanTree(spans: LogTraceSpan[]): LogTraceSpan[] {
  const childMap = new Map<string | null, LogTraceSpan[]>();
  for (const s of spans) {
    const pid = s.parent_span_id ?? null;
    if (!childMap.has(pid)) childMap.set(pid, []);
    childMap.get(pid)!.push(s);
  }
  return childMap.get(null) ?? spans;
}

function getChildren(spans: LogTraceSpan[], parentId: string): LogTraceSpan[] {
  return spans.filter((s) => s.parent_span_id === parentId);
}

export function LogsTraceDetail({ projectId, traceId, onClose }: Props) {
  const [data, setData] = useState<LogTraceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.logs
      .getTraceDetail(projectId, traceId)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "Failed to load trace");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, traceId]);

  if (loading) {
    return (
      <div className="p-4 text-xs text-text-tertiary animate-pulse">
        Loading trace detail...
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="p-4 text-xs text-error">
        {error || "Trace not found"}
      </div>
    );
  }

  const { trace, spans } = data;
  const rootSpans = buildSpanTree(spans);
  const failed = spans.filter((s) => s.status === "failed");

  return (
    <div className="border border-border-subtle rounded-lg bg-surface-0 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 bg-surface-1 border-b border-border-subtle">
        <button
          onClick={onClose}
          className="p-1 rounded-md hover:bg-surface-2 transition-colors text-text-muted"
          aria-label="Close trace detail"
        >
          <Icon name="x" size={14} />
        </button>
        <span className="text-xs font-medium text-text-primary">Trace Detail</span>
        <span className="text-[10px] text-text-muted font-mono">{trace.workflow_id.slice(0, 8)}</span>
        <span
          className={`ml-auto text-[10px] font-medium px-1.5 py-0.5 rounded ${
            trace.status === "completed"
              ? "bg-success/10 text-success"
              : trace.status === "failed"
                ? "bg-error/10 text-error"
                : "bg-info/10 text-info"
          }`}
        >
          {trace.status}
        </span>
      </div>

      <div className="px-4 py-3 border-b border-border-subtle space-y-2">
        <p className="text-sm text-text-primary">{trace.question || "(no question)"}</p>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-text-muted">
          <span>Type: {trace.response_type}</span>
          <span>Model: {trace.llm_model}</span>
          <span>Provider: {trace.llm_provider}</span>
          <span>Steps: {trace.steps_used}/{trace.steps_total}</span>
          <span>Tokens: {trace.total_tokens.toLocaleString()}</span>
          {trace.total_duration_ms != null && (
            <span>Duration: {trace.total_duration_ms >= 1000 ? `${(trace.total_duration_ms / 1000).toFixed(1)}s` : `${Math.round(trace.total_duration_ms)}ms`}</span>
          )}
          {trace.estimated_cost_usd != null && trace.estimated_cost_usd > 0 && (
            <span>Cost: ${trace.estimated_cost_usd < 0.01 ? trace.estimated_cost_usd.toFixed(4) : trace.estimated_cost_usd.toFixed(2)}</span>
          )}
        </div>
        {trace.error_message && (
          <div className="text-xs text-error bg-error/5 rounded-md px-3 py-2">
            {trace.error_message}
          </div>
        )}
      </div>

      {failed.length > 0 && (
        <div className="px-4 py-2 bg-error/5 border-b border-border-subtle">
          <span className="text-[10px] font-medium text-error">
            {failed.length} failed span{failed.length > 1 ? "s" : ""}
          </span>
        </div>
      )}

      <div className="px-2 py-2">
        <div className="text-[10px] text-text-tertiary uppercase tracking-wider px-2 py-1 mb-1">
          Spans ({spans.length})
        </div>
        <div role="tree" aria-label="Trace spans">
          {rootSpans.map((span) => (
            <LogsSpanRow
              key={span.id}
              span={span}
              childSpans={getChildren(spans, span.id)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
