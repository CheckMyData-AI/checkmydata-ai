"use client";

import React, { useState, useCallback } from "react";

export interface LossData {
  loss_type: string;
  title: string;
  description: string;
  metric: string;
  current_value: number;
  expected_value: number;
  loss_amount: number;
  loss_pct: number;
  estimated_monthly_impact: string;
  suggested_fix: string;
  confidence: number;
  evidence: string[];
  severity: string;
}

interface LossReportCardProps {
  losses: LossData[];
  onDrillDown?: (question: string) => void;
}

const TYPE_CONFIG: Record<
  string,
  { icon: string; color: string; bg: string; border: string }
> = {
  funnel_drop: {
    icon: "📉",
    color: "text-red-400",
    bg: "bg-red-950/30",
    border: "border-red-900/40",
  },
  spend_inefficiency: {
    icon: "💸",
    color: "text-orange-400",
    bg: "bg-orange-950/30",
    border: "border-orange-900/40",
  },
  revenue_regression: {
    icon: "📊",
    color: "text-amber-400",
    bg: "bg-amber-950/30",
    border: "border-amber-900/40",
  },
  high_churn: {
    icon: "🚪",
    color: "text-rose-400",
    bg: "bg-rose-950/30",
    border: "border-rose-900/40",
  },
};

const DEFAULT_TYPE = {
  icon: "⚠️",
  color: "text-zinc-400",
  bg: "bg-zinc-800/50",
  border: "border-zinc-700/50",
};

function drillQuestion(loss: LossData): string {
  if (loss.loss_type === "funnel_drop") {
    return `Show me a detailed breakdown of ${loss.metric} at each funnel step — where exactly are we losing users?`;
  }
  if (loss.loss_type === "spend_inefficiency") {
    return `Break down the ROI for each channel including ${loss.metric} — which ones should we cut or scale?`;
  }
  if (loss.loss_type === "revenue_regression") {
    return `Show me the ${loss.metric} trend over time — when exactly did the decline start and what changed?`;
  }
  return `Investigate why ${loss.metric} is declining — show me contributing factors`;
}

export function LossReportCard({
  losses,
  onDrillDown,
}: LossReportCardProps) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  const handleToggle = useCallback((idx: number) => {
    setExpandedIdx((prev) => (prev === idx ? null : idx));
  }, []);

  if (!losses || losses.length === 0) return null;

  return (
    <div className="mt-2 space-y-1.5">
      <div className="flex items-center gap-1.5 text-[11px] text-zinc-500 font-medium uppercase tracking-wider">
        <span>🩸</span>
        Losses Detected ({losses.length})
      </div>
      {losses.map((loss, idx) => {
        const cfg = TYPE_CONFIG[loss.loss_type] || DEFAULT_TYPE;
        const isExpanded = expandedIdx === idx;
        const confidencePct = Math.round(loss.confidence * 100);

        return (
          <div
            key={idx}
            className={`rounded-lg border ${cfg.border} ${cfg.bg} transition-all`}
          >
            <button
              onClick={() => handleToggle(idx)}
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] w-full text-left"
            >
              <span className="shrink-0">{cfg.icon}</span>
              <span
                className={`font-medium truncate ${cfg.color}`}
                title={loss.title}
              >
                {loss.title}
              </span>
              <span className="ml-auto flex items-center gap-1 shrink-0">
                <span className="text-[10px] px-1 py-0.5 rounded bg-red-900/40 text-red-400">
                  -{loss.loss_pct}%
                </span>
                <span className="text-[10px] text-zinc-500 tabular-nums">
                  {confidencePct}%
                </span>
              </span>
              <svg
                className={`w-3 h-3 text-zinc-500 transition-transform shrink-0 ${isExpanded ? "rotate-180" : ""}`}
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
              <div className="px-2.5 pb-2 space-y-1.5 border-t border-zinc-800/50">
                <p className="text-[11px] text-zinc-400 leading-relaxed pt-1.5">
                  {loss.description}
                </p>

                {loss.estimated_monthly_impact && (
                  <div className="flex gap-1.5 text-[11px]">
                    <span className="text-zinc-500 shrink-0">💰 Impact:</span>
                    <span className="text-red-300">{loss.estimated_monthly_impact}</span>
                  </div>
                )}

                {loss.suggested_fix && (
                  <div className="flex gap-1.5 text-[11px]">
                    <span className="text-zinc-500 shrink-0">→ Fix:</span>
                    <span className="text-emerald-400">{loss.suggested_fix}</span>
                  </div>
                )}

                {loss.evidence.length > 0 && (
                  <div className="flex flex-wrap gap-1 pt-0.5">
                    {loss.evidence.map((e, i) => (
                      <span
                        key={i}
                        className="text-[10px] px-1.5 py-0.5 bg-zinc-800/60 rounded text-zinc-500"
                      >
                        {e}
                      </span>
                    ))}
                  </div>
                )}

                {onDrillDown && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDrillDown(drillQuestion(loss));
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
