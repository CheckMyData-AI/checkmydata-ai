"use client";

import React, { useState, useEffect, useCallback } from "react";
import { api, type InsightDTO } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";
import { Icon } from "@/components/ui/Icon";

const SEVERITY_CONFIG: Record<string, { color: string; bg: string; border: string; label: string }> = {
  critical: {
    color: "text-error",
    bg: "bg-error-muted",
    border: "border-border-default",
    label: "Critical",
  },
  warning: {
    color: "text-warning",
    bg: "bg-warning-muted",
    border: "border-border-default",
    label: "Warning",
  },
  info: {
    color: "text-accent",
    bg: "bg-accent-muted",
    border: "border-border-default",
    label: "Info",
  },
  positive: {
    color: "text-success",
    bg: "bg-success-muted",
    border: "border-border-default",
    label: "Opportunity",
  },
};

type IconName = Parameters<typeof Icon>[0]["name"];

const TYPE_ICONS: Record<string, IconName> = {
  anomaly: "alert-triangle",
  opportunity: "arrow-up",
  loss: "arrow-down",
  trend: "activity",
  pattern: "git-branch",
  reconciliation_mismatch: "layers",
  data_quality: "shield",
  observation: "search",
};

function ConfidenceBadge({ confidence }: { confidence: number }) {
  let label: string;
  let cls: string;
  if (confidence >= 0.85) {
    label = "High";
    cls = "text-success bg-success-muted border-border-default";
  } else if (confidence >= 0.6) {
    label = "Medium";
    cls = "text-accent bg-accent-muted border-border-default";
  } else if (confidence >= 0.3) {
    label = "Low";
    cls = "text-warning bg-warning-muted border-border-default";
  } else {
    label = "Very low";
    cls = "text-text-secondary bg-surface-2/50 border-border-default/50";
  }
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium rounded border ${cls}`}>
      {label} ({Math.round(confidence * 100)}%)
    </span>
  );
}

function InsightCard({
  insight,
  onConfirm,
  onDismiss,
  onResolve,
  onDrillDown,
}: {
  insight: InsightDTO;
  onConfirm: (id: string) => void;
  onDismiss: (id: string) => void;
  onResolve: (id: string) => void;
  onDrillDown?: (question: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const cfg = SEVERITY_CONFIG[insight.severity] || SEVERITY_CONFIG.info;
  const iconName = TYPE_ICONS[insight.insight_type] || "info";

  return (
    <div className={`rounded-xl border ${cfg.border} ${cfg.bg} transition-all`}>
      <button
        onClick={() => setExpanded((p) => !p)}
        className={`flex items-start gap-2 px-3 py-2 w-full text-left`}
      >
        <Icon name={iconName} size={14} className={`${cfg.color} mt-0.5 shrink-0`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-xs font-medium ${cfg.color}`}>{cfg.label}</span>
            <ConfidenceBadge confidence={insight.confidence} />
            {insight.times_surfaced > 1 && (
              <span className="text-[10px] text-text-muted">
                seen {insight.times_surfaced}x
              </span>
            )}
          </div>
          <p className="text-sm text-text-primary font-medium mt-0.5 leading-snug">
            {insight.title}
          </p>
        </div>
        <Icon
          name={expanded ? "chevron-up" : "chevron-down"}
          size={14}
          className="text-text-muted mt-1 shrink-0"
        />
      </button>

      {expanded && (
        <div className="px-3 pb-2.5 space-y-2">
          <p className="text-xs text-text-secondary leading-relaxed">
            {insight.description}
          </p>

          {insight.recommended_action && (
            <div className="rounded-md bg-surface-1 border border-border-subtle px-2.5 py-1.5">
              <p className="text-[10px] text-text-muted uppercase tracking-wider mb-0.5">
                Recommended action
              </p>
              <p className="text-xs text-text-primary">{insight.recommended_action}</p>
              {insight.expected_impact && (
                <p className="text-[11px] text-success mt-0.5">
                  Expected: {insight.expected_impact}
                </p>
              )}
            </div>
          )}

          <div className="flex items-center gap-1.5 pt-1">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onConfirm(insight.id);
              }}
              className="text-[11px] px-2 py-0.5 rounded border border-border-default text-success bg-success-muted hover:bg-success-muted transition-colors"
            >
              Confirm
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDismiss(insight.id);
              }}
              className="text-[11px] px-2 py-0.5 rounded border border-border-default/50 text-text-secondary bg-surface-2/50 hover:bg-surface-3/50 transition-colors"
            >
              Dismiss
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onResolve(insight.id);
              }}
              className="text-[11px] px-2 py-0.5 rounded border border-border-default text-accent bg-accent-muted hover:bg-accent-muted transition-colors"
            >
              Resolved
            </button>
            {onDrillDown && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDrillDown(`Tell me more about: ${insight.title}`);
                }}
                className="text-[11px] px-2 py-0.5 rounded border border-accent/30 text-accent bg-accent-muted hover:bg-accent/20 transition-colors ml-auto"
              >
                Investigate
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

interface InsightFeedPanelProps {
  onDrillDown?: (question: string) => void;
}

export function InsightFeedPanel({ onDrillDown }: InsightFeedPanelProps) {
  const { activeProject } = useAppStore();
  const [insights, setInsights] = useState<InsightDTO[]>([]);
  const [summary, setSummary] = useState<{
    total_active: number;
    by_type: Record<string, number>;
    by_severity: Record<string, number>;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [filter, setFilter] = useState<string>("all");

  const loadInsights = useCallback(async () => {
    if (!activeProject) return;
    setLoading(true);
    setLoadError(false);
    try {
      const params: Record<string, string> = {};
      if (filter !== "all") params.severity = filter;
      const [data, sum] = await Promise.all([
        api.insights.list(activeProject.id, { ...params, limit: 50 }),
        api.insights.summary(activeProject.id),
      ]);
      setInsights(data);
      setSummary(sum);
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, [activeProject, filter]);

  useEffect(() => {
    loadInsights();
  }, [loadInsights]);

  const handleConfirm = useCallback(
    async (id: string) => {
      if (!activeProject) return;
      try {
        await api.insights.confirm(activeProject.id, id);
        toast("Insight confirmed", "success");
        loadInsights();
      } catch {
        toast("Failed to confirm insight", "error");
      }
    },
    [activeProject, loadInsights],
  );

  const handleDismiss = useCallback(
    async (id: string) => {
      if (!activeProject) return;
      try {
        await api.insights.dismiss(activeProject.id, id);
        toast("Insight dismissed", "success");
        loadInsights();
      } catch {
        toast("Failed to dismiss insight", "error");
      }
    },
    [activeProject, loadInsights],
  );

  const handleResolve = useCallback(
    async (id: string) => {
      if (!activeProject) return;
      try {
        await api.insights.resolve(activeProject.id, id);
        toast("Insight marked as resolved", "success");
        loadInsights();
      } catch {
        toast("Failed to resolve insight", "error");
      }
    },
    [activeProject, loadInsights],
  );

  if (!activeProject) return null;

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 border-b border-border-subtle">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
            Insights
          </h3>
          {summary && summary.total_active > 0 && (
            <span className="text-[10px] text-text-muted">
              {summary.total_active} active
            </span>
          )}
        </div>
        {summary && summary.total_active > 0 && (
          <div className="flex gap-1 mt-1.5 flex-wrap">
            {(["all", "critical", "warning", "info", "positive"] as const).map((s) => {
              const count =
                s === "all"
                  ? summary.total_active
                  : summary.by_severity[s] || 0;
              if (s !== "all" && count === 0) return null;
              return (
                <button
                  key={s}
                  onClick={() => setFilter(s)}
                  className={`text-[10px] px-1.5 py-0.5 rounded transition-colors ${
                    filter === s
                      ? "bg-accent text-white"
                      : "bg-surface-2 text-text-secondary hover:bg-surface-3"
                  }`}
                >
                  {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
                  {count > 0 && ` (${count})`}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
        {loading && insights.length === 0 && (
          <div className="flex items-center justify-center py-8">
            <div className="w-4 h-4 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          </div>
        )}

        {!loading && loadError && (
          <div className="text-center py-4 px-4">
            <Icon name="alert-triangle" size={24} className="mx-auto text-warning mb-2" />
            <p className="text-xs text-text-tertiary mb-2">
              Couldn&apos;t load insights
            </p>
            <button
              onClick={loadInsights}
              className="text-[11px] text-accent hover:text-accent-hover transition-colors"
            >
              Retry
            </button>
          </div>
        )}

        {!loading && !loadError && insights.length === 0 && (
          <div className="text-center py-8 px-4">
            <Icon name="zap" size={24} className="mx-auto text-text-muted mb-2" />
            <p className="text-xs text-text-tertiary">
              No insights yet. Insights will appear here as the system analyzes your data.
            </p>
          </div>
        )}

        {insights.map((insight) => (
          <InsightCard
            key={insight.id}
            insight={insight}
            onConfirm={handleConfirm}
            onDismiss={handleDismiss}
            onResolve={handleResolve}
            onDrillDown={onDrillDown}
          />
        ))}
      </div>
    </div>
  );
}
