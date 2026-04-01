"use client";

import { useState, useCallback } from "react";
import type { SQLResultBlock, RawResult } from "@/stores/app-store";
import { useAppStore } from "@/stores/app-store";
import { VizRenderer } from "@/components/viz/VizRenderer";
import { VizToolbar } from "@/components/viz/VizToolbar";
import { DataTable } from "@/components/viz/DataTable";
import { rerenderViz, type VizTypeKey } from "@/lib/viz-utils";
import { toast } from "@/stores/toast-store";
import { InsightCards, type Insight } from "./InsightCards";
import { SQLExplainer } from "./SQLExplainer";

function resolveOriginalVizType(
  visualization: Record<string, unknown> | null | undefined,
): VizTypeKey {
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

interface SQLResultSectionProps {
  block: SQLResultBlock;
  index: number;
  total: number;
  onSendMessage?: (text: string) => void;
}

export function SQLResultSection({ block, index, total, onSendMessage }: SQLResultSectionProps) {
  const hasViz = !!block.visualization;
  const hasRawResult = !!block.rawResult;
  const originalVizType = resolveOriginalVizType(block.visualization);
  const [activeVizType, setActiveVizType] = useState<VizTypeKey>(originalVizType);
  const [overrideViz, setOverrideViz] = useState<Record<string, unknown> | null>(null);
  const [vizLoading, setVizLoading] = useState(false);
  const [viewMode, setViewMode] = useState<"viz" | "text">(hasViz ? "viz" : "text");
  const [mobileVizExpanded, setMobileVizExpanded] = useState(false);

  const sqlComplexity = block.query ? computeSqlComplexity(block.query) : null;

  const handleVizTypeChange = useCallback(
    async (newType: VizTypeKey) => {
      if (newType === activeVizType || !block.rawResult) return;
      const previousType = activeVizType;
      setActiveVizType(newType);

      if (newType === originalVizType) {
        setOverrideViz(null);
        return;
      }

      setVizLoading(true);
      try {
        const newViz = await rerenderViz(block.rawResult as RawResult, newType);
        setOverrideViz(newViz);
      } catch (err) {
        toast(err instanceof Error ? err.message : "Failed to re-render visualization", "error");
        setActiveVizType(previousType);
      } finally {
        setVizLoading(false);
      }
    },
    [activeVizType, originalVizType, block.rawResult],
  );

  const projectId = useAppStore.getState().activeProject?.id ?? "";

  return (
    <div className={total > 1 ? "mt-3 pt-3 border-t border-border-subtle first:mt-0 first:pt-0 first:border-t-0" : ""}>
      {total > 1 && (
        <div className="mb-2 text-[10px] font-medium text-text-secondary uppercase tracking-wide">
          Query {index + 1} of {total}
        </div>
      )}

      {block.query && (
        <details className="mt-1 text-xs">
          <summary className="cursor-pointer text-text-secondary hover:text-text-primary flex items-center gap-2">
            View SQL Query
            {sqlComplexity && (
              <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${complexityBadgeColors[sqlComplexity] || ""}`}>
                {sqlComplexity.charAt(0).toUpperCase() + sqlComplexity.slice(1)}
              </span>
            )}
          </summary>
          <pre className="mt-2 p-3 bg-surface-1 rounded-lg overflow-x-auto max-w-full text-text-primary">
            {block.query}
          </pre>
          {block.queryExplanation && (
            <p className="mt-1 text-text-secondary">{block.queryExplanation}</p>
          )}
          <SQLExplainer sql={block.query} projectId={projectId} />
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
                <VizRenderer data={overrideViz ?? block.visualization!} />
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
            <VizRenderer data={overrideViz ?? block.visualization!} />
          </div>
        </div>
      )}

      {hasViz && viewMode === "text" && hasRawResult && (
        <div className="mt-2">
          <DataTable
            data={{
              columns: block.rawResult!.columns,
              rows: block.rawResult!.rows.map((row) =>
                Object.fromEntries(
                  block.rawResult!.columns.map((col, i) => [col, row[i]]),
                ),
              ),
              total_rows: block.rawResult!.total_rows,
            }}
          />
        </div>
      )}

      {block.insights && block.insights.length > 0 && (
        <InsightCards insights={block.insights as Insight[]} onDrillDown={onSendMessage} />
      )}
    </div>
  );
}
