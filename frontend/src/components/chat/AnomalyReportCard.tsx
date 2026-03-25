"use client";

import React, { useState, useCallback } from "react";

export interface AnomalyReport {
  check_type: string;
  title: string;
  description: string;
  severity: string;
  business_impact: string;
  root_cause_hypothesis: string;
  affected_metrics: string[];
  affected_rows: number;
  confidence: number;
  recommended_action: string;
  expected_impact: string;
  related_anomalies: string[];
}

interface AnomalyReportCardProps {
  reports: AnomalyReport[];
  onDrillDown?: (question: string) => void;
}

const SEVERITY_CONFIG: Record<
  string,
  { color: string; bg: string; border: string; icon: string; label: string }
> = {
  critical: {
    color: "text-error",
    bg: "bg-error-muted",
    border: "border-border-default",
    icon: "🔴",
    label: "Critical",
  },
  warning: {
    color: "text-warning",
    bg: "bg-warning-muted",
    border: "border-border-default",
    icon: "🟡",
    label: "Warning",
  },
  info: {
    color: "text-accent",
    bg: "bg-accent-muted",
    border: "border-border-default",
    icon: "ℹ️",
    label: "Info",
  },
};

const DEFAULT_SEVERITY = {
  color: "text-text-secondary",
  bg: "bg-surface-2",
  border: "border-border-default",
  icon: "❓",
  label: "Unknown",
};

function drillDownQuestion(report: AnomalyReport): string {
  const metric =
    report.affected_metrics[0] || "the affected metric";
  if (report.check_type === "all_null") {
    return `Why is ${metric} entirely NULL? Show me if there's related data in other tables`;
  }
  if (report.check_type === "negative_value") {
    return `Show me all negative values in ${metric} with their context — are these refunds or errors?`;
  }
  if (report.check_type === "duplicate_keys") {
    return `Show me the duplicate entries and which groups are affected`;
  }
  return `Investigate ${metric} — ${report.root_cause_hypothesis}`;
}

export function AnomalyReportCard({
  reports,
  onDrillDown,
}: AnomalyReportCardProps) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(
    null,
  );

  const handleToggle = useCallback((idx: number) => {
    setExpandedIdx((prev) => (prev === idx ? null : idx));
  }, []);

  if (!reports || reports.length === 0) return null;

  return (
    <div className="mt-2 space-y-1.5">
      <div className="flex items-center gap-1.5 text-[11px] text-text-tertiary font-medium uppercase tracking-wider">
        <svg
          className="w-3 h-3"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
          />
        </svg>
        Anomaly Intelligence ({reports.length})
      </div>
      {reports.map((report, idx) => {
        const cfg =
          SEVERITY_CONFIG[report.severity] || DEFAULT_SEVERITY;
        const isExpanded = expandedIdx === idx;
        const confidencePct = Math.round(report.confidence * 100);

        return (
          <div
            key={idx}
            className={`rounded-xl border ${cfg.border} ${cfg.bg} transition-all`}
          >
            <button
              onClick={() => handleToggle(idx)}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] w-full text-left`}
            >
              <span className="shrink-0">{cfg.icon}</span>
              <span
                className={`font-medium truncate ${cfg.color}`}
                title={report.title}
              >
                {report.title}
              </span>
              <span className="ml-auto shrink-0 text-[10px] text-text-tertiary tabular-nums">
                {confidencePct}%
              </span>
              <svg
                className={`w-3 h-3 text-text-tertiary transition-transform shrink-0 ${isExpanded ? "rotate-180" : ""}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M19 9l-7 7-7-7"
                />
              </svg>
            </button>

            {isExpanded && (
              <div className="px-2.5 pb-2 space-y-1.5 border-t border-border-subtle">
                <p className="text-[11px] text-text-secondary leading-relaxed pt-1.5">
                  {report.description}
                </p>

                {report.root_cause_hypothesis && (
                  <div className="flex gap-1.5 text-[11px]">
                    <span className="text-text-tertiary shrink-0">
                      💡 Root cause:
                    </span>
                    <span className="text-text-primary">
                      {report.root_cause_hypothesis}
                    </span>
                  </div>
                )}

                {report.business_impact && (
                  <div className="flex gap-1.5 text-[11px]">
                    <span className="text-text-tertiary shrink-0">
                      📊 Impact:
                    </span>
                    <span className="text-text-primary">
                      {report.business_impact}
                    </span>
                  </div>
                )}

                {report.recommended_action && (
                  <div className="flex gap-1.5 text-[11px]">
                    <span className="text-text-tertiary shrink-0">
                      → Action:
                    </span>
                    <span className="text-success">
                      {report.recommended_action}
                    </span>
                  </div>
                )}

                {report.expected_impact && (
                  <div className="flex gap-1.5 text-[11px]">
                    <span className="text-text-tertiary shrink-0">
                      ✨ Expected:
                    </span>
                    <span className="text-text-primary">
                      {report.expected_impact}
                    </span>
                  </div>
                )}

                <div className="flex items-center gap-2 pt-0.5">
                  {report.affected_rows > 0 && (
                    <span className="text-[10px] text-text-tertiary">
                      {report.affected_rows} rows affected
                    </span>
                  )}
                  {report.affected_metrics.length > 0 && (
                    <span className="text-[10px] text-text-tertiary">
                      Metric:{" "}
                      {report.affected_metrics.join(", ")}
                    </span>
                  )}
                </div>

                {onDrillDown && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDrillDown(drillDownQuestion(report));
                      setExpandedIdx(null);
                    }}
                    className={`text-[10px] px-1.5 py-0.5 rounded border ${cfg.border} ${cfg.color} hover:brightness-125 transition-all`}
                  >
                    Investigate further
                  </button>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
