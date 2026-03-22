"use client";

import React, { useState } from "react";

export interface FindingData {
  category: string;
  severity: string;
  title: string;
  description: string;
  evidence: string;
  recommended_action: string;
  confidence: number;
  source: string;
}

export interface InvestigationReportData {
  status: string;
  total_findings: number;
  critical_count: number;
  warning_count: number;
  positive_count: number;
  findings: FindingData[];
  summary: string;
  investigation_steps: string[];
  data_coverage: Record<string, number>;
}

interface ExplorationReportProps {
  report: InvestigationReportData;
  onDrillDown?: (question: string) => void;
}

const STATUS_CONFIG: Record<
  string,
  { icon: string; color: string; bg: string; border: string; label: string }
> = {
  issues_found: {
    icon: "⚠️",
    color: "text-amber-400",
    bg: "bg-amber-950/30",
    border: "border-amber-900/40",
    label: "Issues Found",
  },
  healthy: {
    icon: "✅",
    color: "text-emerald-400",
    bg: "bg-emerald-950/30",
    border: "border-emerald-900/40",
    label: "All Healthy",
  },
  partial: {
    icon: "🔍",
    color: "text-blue-400",
    bg: "bg-blue-950/30",
    border: "border-blue-900/40",
    label: "Partial Analysis",
  },
};

const SEVERITY_CONFIG: Record<string, { icon: string; color: string }> = {
  critical: { icon: "🔴", color: "text-red-400" },
  warning: { icon: "🟡", color: "text-amber-400" },
  info: { icon: "🔵", color: "text-blue-400" },
  positive: { icon: "🟢", color: "text-emerald-400" },
};

const CATEGORY_ICON: Record<string, string> = {
  anomaly: "📊",
  opportunity: "📈",
  loss: "📉",
  reconciliation: "🔄",
  health: "🏥",
  trend: "📈",
  general: "💡",
};

export function ExplorationReport({ report, onDrillDown }: ExplorationReportProps) {
  const [showSteps, setShowSteps] = useState(false);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const statusCfg = STATUS_CONFIG[report.status] || STATUS_CONFIG.partial;

  return (
    <div className={`mt-2 rounded-lg border ${statusCfg.border} ${statusCfg.bg} overflow-hidden`}>
      {/* Header */}
      <div className="px-2.5 py-1.5 flex items-center gap-1.5 text-[11px]">
        <span>{statusCfg.icon}</span>
        <span className={`font-medium ${statusCfg.color}`}>
          Exploration Report: {statusCfg.label}
        </span>
        <span className="ml-auto text-zinc-500">
          {report.total_findings} findings
        </span>
      </div>

      {/* Summary */}
      <div className="px-2.5 pb-1.5 text-[11px] text-zinc-400 leading-relaxed">
        {report.summary}
      </div>

      {/* Badge row */}
      <div className="px-2.5 pb-1.5 flex gap-1.5 flex-wrap">
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
        {report.positive_count > 0 && (
          <span className="text-[10px] px-1 py-0.5 rounded bg-emerald-900/40 text-emerald-400">
            {report.positive_count} positive
          </span>
        )}
        <button
          onClick={() => setShowSteps(!showSteps)}
          className="text-[10px] px-1 py-0.5 rounded bg-zinc-800/50 text-zinc-500 hover:text-zinc-300 transition-all"
        >
          {showSteps ? "Hide" : "Show"} steps ({report.investigation_steps.length})
        </button>
      </div>

      {/* Investigation steps */}
      {showSteps && (
        <div className="px-2.5 pb-1.5 border-t border-zinc-800/50">
          <ol className="list-decimal list-inside text-[10px] text-zinc-500 space-y-0.5 pt-1">
            {report.investigation_steps.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </div>
      )}

      {/* Findings */}
      {report.findings.length > 0 && (
        <div className="border-t border-zinc-800/50">
          {report.findings.map((finding, idx) => {
            const isExpanded = expandedIdx === idx;
            const sevCfg = SEVERITY_CONFIG[finding.severity] || SEVERITY_CONFIG.info;
            const catIcon = CATEGORY_ICON[finding.category] || CATEGORY_ICON.general;

            return (
              <div key={idx} className="border-b border-zinc-800/30 last:border-b-0">
                <button
                  onClick={() => setExpandedIdx(isExpanded ? null : idx)}
                  className="flex items-center gap-1.5 px-2.5 py-1 text-[11px] w-full text-left"
                >
                  <span className="text-[10px] shrink-0">{sevCfg.icon}</span>
                  <span className="text-[10px] shrink-0">{catIcon}</span>
                  <span className={`${sevCfg.color} truncate`} title={finding.title}>
                    {finding.title}
                  </span>
                  <span className="ml-auto text-[9px] text-zinc-600 shrink-0">
                    {Math.round(finding.confidence * 100)}%
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
                    {finding.description && (
                      <div className="text-zinc-400 leading-relaxed">
                        {finding.description}
                      </div>
                    )}
                    {finding.evidence && (
                      <div className="flex gap-1.5">
                        <span className="text-zinc-500 shrink-0">Evidence:</span>
                        <span className="text-zinc-300">{finding.evidence}</span>
                      </div>
                    )}
                    {finding.recommended_action && (
                      <div className="flex gap-1.5">
                        <span className="text-zinc-500 shrink-0">Action:</span>
                        <span className="text-emerald-400">{finding.recommended_action}</span>
                      </div>
                    )}
                    {onDrillDown && finding.severity !== "positive" && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onDrillDown(`Investigate: ${finding.title}`);
                          setExpandedIdx(null);
                        }}
                        className="text-[10px] px-1.5 py-0.5 rounded border border-zinc-700 text-zinc-400 hover:text-zinc-200 transition-all"
                      >
                        Dig deeper
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
