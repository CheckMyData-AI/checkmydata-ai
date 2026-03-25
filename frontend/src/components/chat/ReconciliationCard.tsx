"use client";

import React, { useState, useCallback } from "react";

export interface DiscrepancyData {
  discrepancy_type: string;
  severity: string;
  title: string;
  description: string;
  source_a_name: string;
  source_b_name: string;
  source_a_value: unknown;
  source_b_value: unknown;
  affected_metric: string;
  affected_table: string;
  difference_pct: number;
  likely_cause: string;
  recommended_action: string;
}

export interface ReconciliationReportData {
  source_a_name: string;
  source_b_name: string;
  status: string;
  total_checks: number;
  critical_count: number;
  warning_count: number;
  discrepancies: DiscrepancyData[];
  summary: string;
}

interface ReconciliationCardProps {
  report: ReconciliationReportData;
  onDrillDown?: (question: string) => void;
}

const STATUS_CONFIG: Record<
  string,
  { icon: string; color: string; bg: string; border: string }
> = {
  clean: {
    icon: "✅",
    color: "text-success",
    bg: "bg-success-muted",
    border: "border-border-default",
  },
  discrepancies_found: {
    icon: "⚠️",
    color: "text-warning",
    bg: "bg-warning-muted",
    border: "border-border-default",
  },
  error: {
    icon: "❌",
    color: "text-error",
    bg: "bg-error-muted",
    border: "border-border-default",
  },
};

const SEVERITY_BADGE: Record<string, string> = {
  critical: "bg-error-muted text-error",
  warning: "bg-warning-muted text-warning",
  info: "bg-accent-muted text-accent",
};

const TYPE_LABEL: Record<string, string> = {
  count_diff: "Row Count",
  value_mismatch: "Value Mismatch",
  schema_diff: "Schema Diff",
  missing_records: "Missing Records",
};

export function ReconciliationCard({ report, onDrillDown }: ReconciliationCardProps) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const statusCfg = STATUS_CONFIG[report.status] || STATUS_CONFIG.error;

  const handleToggle = useCallback((idx: number) => {
    setExpandedIdx((prev) => (prev === idx ? null : idx));
  }, []);

  return (
    <div className={`mt-2 rounded-xl border ${statusCfg.border} ${statusCfg.bg} overflow-hidden`}>
      {/* Header */}
      <div className="px-2.5 py-1.5 flex items-center gap-1.5 text-[11px]">
        <span>{statusCfg.icon}</span>
        <span className={`font-medium ${statusCfg.color}`}>
          Reconciliation: {report.source_a_name} vs {report.source_b_name}
        </span>
        <span className="ml-auto text-text-tertiary">
          {report.total_checks} checks
        </span>
      </div>

      {/* Summary */}
      <div className="px-2.5 pb-1.5 text-[11px] text-text-secondary leading-relaxed">
        {report.summary}
      </div>

      {/* Badge row */}
      {(report.critical_count > 0 || report.warning_count > 0) && (
        <div className="px-2.5 pb-1.5 flex gap-1.5">
          {report.critical_count > 0 && (
            <span className="text-[10px] px-1 py-0.5 rounded bg-error-muted text-error">
              {report.critical_count} critical
            </span>
          )}
          {report.warning_count > 0 && (
            <span className="text-[10px] px-1 py-0.5 rounded bg-warning-muted text-warning">
              {report.warning_count} warnings
            </span>
          )}
        </div>
      )}

      {/* Discrepancy list */}
      {report.discrepancies.length > 0 && (
        <div className="border-t border-border-subtle">
          {report.discrepancies.map((disc, idx) => {
            const isExpanded = expandedIdx === idx;
            const sevClass = SEVERITY_BADGE[disc.severity] || SEVERITY_BADGE.info;
            const typeLabel = TYPE_LABEL[disc.discrepancy_type] || disc.discrepancy_type;

            return (
              <div key={idx} className="border-b border-border-subtle last:border-b-0">
                <button
                  onClick={() => handleToggle(idx)}
                  className="flex items-center gap-1.5 px-2.5 py-1 text-[11px] w-full text-left"
                >
                  <span className={`text-[10px] px-1 py-0.5 rounded shrink-0 ${sevClass}`}>
                    {disc.severity}
                  </span>
                  <span className="text-text-primary truncate" title={disc.title}>
                    {disc.title}
                  </span>
                  <span className="ml-auto text-[10px] text-text-muted shrink-0">
                    {typeLabel}
                  </span>
                  <svg
                    className={`w-3 h-3 text-text-tertiary transition-transform shrink-0 ${isExpanded ? "rotate-180" : ""}`}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </button>

                {isExpanded && (
                  <div className="px-2.5 pb-1.5 space-y-1 text-[11px]">
                    <div className="text-text-secondary leading-relaxed">{disc.description}</div>

                    {disc.difference_pct > 0 && (
                      <div className="flex gap-1.5">
                        <span className="text-text-tertiary">Difference:</span>
                        <span className="text-warning">{disc.difference_pct}%</span>
                      </div>
                    )}

                    {disc.likely_cause && (
                      <div className="flex gap-1.5">
                        <span className="text-text-tertiary shrink-0">Likely cause:</span>
                        <span className="text-text-primary">{disc.likely_cause}</span>
                      </div>
                    )}

                    {disc.recommended_action && (
                      <div className="flex gap-1.5">
                        <span className="text-text-tertiary shrink-0">Action:</span>
                        <span className="text-success">{disc.recommended_action}</span>
                      </div>
                    )}

                    {onDrillDown && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onDrillDown(
                            `Investigate reconciliation discrepancy: ${disc.title}`
                          );
                          setExpandedIdx(null);
                        }}
                        className="text-[10px] px-1.5 py-0.5 rounded border border-border-default text-text-secondary hover:text-text-primary transition-all"
                      >
                        Investigate this
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
