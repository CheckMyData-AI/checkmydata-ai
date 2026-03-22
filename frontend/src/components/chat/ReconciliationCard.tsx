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
    color: "text-emerald-400",
    bg: "bg-emerald-950/30",
    border: "border-emerald-900/40",
  },
  discrepancies_found: {
    icon: "⚠️",
    color: "text-amber-400",
    bg: "bg-amber-950/30",
    border: "border-amber-900/40",
  },
  error: {
    icon: "❌",
    color: "text-red-400",
    bg: "bg-red-950/30",
    border: "border-red-900/40",
  },
};

const SEVERITY_BADGE: Record<string, string> = {
  critical: "bg-red-900/40 text-red-400",
  warning: "bg-amber-900/40 text-amber-400",
  info: "bg-blue-900/40 text-blue-400",
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
    <div className={`mt-2 rounded-lg border ${statusCfg.border} ${statusCfg.bg} overflow-hidden`}>
      {/* Header */}
      <div className="px-2.5 py-1.5 flex items-center gap-1.5 text-[11px]">
        <span>{statusCfg.icon}</span>
        <span className={`font-medium ${statusCfg.color}`}>
          Reconciliation: {report.source_a_name} vs {report.source_b_name}
        </span>
        <span className="ml-auto text-zinc-500">
          {report.total_checks} checks
        </span>
      </div>

      {/* Summary */}
      <div className="px-2.5 pb-1.5 text-[11px] text-zinc-400 leading-relaxed">
        {report.summary}
      </div>

      {/* Badge row */}
      {(report.critical_count > 0 || report.warning_count > 0) && (
        <div className="px-2.5 pb-1.5 flex gap-1.5">
          {report.critical_count > 0 && (
            <span className="text-[10px] px-1 py-0.5 rounded bg-red-900/40 text-red-400">
              {report.critical_count} critical
            </span>
          )}
          {report.warning_count > 0 && (
            <span className="text-[10px] px-1 py-0.5 rounded bg-amber-900/40 text-amber-400">
              {report.warning_count} warnings
            </span>
          )}
        </div>
      )}

      {/* Discrepancy list */}
      {report.discrepancies.length > 0 && (
        <div className="border-t border-zinc-800/50">
          {report.discrepancies.map((disc, idx) => {
            const isExpanded = expandedIdx === idx;
            const sevClass = SEVERITY_BADGE[disc.severity] || SEVERITY_BADGE.info;
            const typeLabel = TYPE_LABEL[disc.discrepancy_type] || disc.discrepancy_type;

            return (
              <div key={idx} className="border-b border-zinc-800/30 last:border-b-0">
                <button
                  onClick={() => handleToggle(idx)}
                  className="flex items-center gap-1.5 px-2.5 py-1 text-[11px] w-full text-left"
                >
                  <span className={`text-[10px] px-1 py-0.5 rounded shrink-0 ${sevClass}`}>
                    {disc.severity}
                  </span>
                  <span className="text-zinc-300 truncate" title={disc.title}>
                    {disc.title}
                  </span>
                  <span className="ml-auto text-[10px] text-zinc-600 shrink-0">
                    {typeLabel}
                  </span>
                  <svg
                    className={`w-3 h-3 text-zinc-500 transition-transform shrink-0 ${isExpanded ? "rotate-180" : ""}`}
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
                    <div className="text-zinc-400 leading-relaxed">{disc.description}</div>

                    {disc.difference_pct > 0 && (
                      <div className="flex gap-1.5">
                        <span className="text-zinc-500">Difference:</span>
                        <span className="text-amber-400">{disc.difference_pct}%</span>
                      </div>
                    )}

                    {disc.likely_cause && (
                      <div className="flex gap-1.5">
                        <span className="text-zinc-500 shrink-0">Likely cause:</span>
                        <span className="text-zinc-300">{disc.likely_cause}</span>
                      </div>
                    )}

                    {disc.recommended_action && (
                      <div className="flex gap-1.5">
                        <span className="text-zinc-500 shrink-0">Action:</span>
                        <span className="text-emerald-400">{disc.recommended_action}</span>
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
                        className="text-[10px] px-1.5 py-0.5 rounded border border-zinc-700 text-zinc-400 hover:text-zinc-200 transition-all"
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
