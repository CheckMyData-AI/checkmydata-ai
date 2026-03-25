"use client";

import React, { useState, useCallback } from "react";

export interface OpportunityData {
  opportunity_type: string;
  title: string;
  description: string;
  segment: string;
  metric: string;
  current_value: number;
  benchmark_value: number;
  gap_pct: number;
  estimated_impact: string;
  suggested_action: string;
  confidence: number;
  evidence: string[];
  severity: string;
}

interface OpportunityCardProps {
  opportunities: OpportunityData[];
  onDrillDown?: (question: string) => void;
}

const TYPE_CONFIG: Record<
  string,
  { icon: string; color: string; bg: string; border: string }
> = {
  high_performer: {
    icon: "🏆",
    color: "text-success",
    bg: "bg-success-muted",
    border: "border-border-default",
  },
  conversion_gap: {
    icon: "📈",
    color: "text-accent",
    bg: "bg-accent-muted",
    border: "border-border-default",
  },
  undermonetized: {
    icon: "💎",
    color: "text-accent",
    bg: "bg-accent-muted",
    border: "border-border-default",
  },
  growth_potential: {
    icon: "🚀",
    color: "text-warning",
    bg: "bg-warning-muted",
    border: "border-border-default",
  },
};

const DEFAULT_TYPE = {
  icon: "💡",
  color: "text-text-secondary",
  bg: "bg-surface-2",
  border: "border-border-default",
};

function drillQuestion(opp: OpportunityData): string {
  if (opp.opportunity_type === "high_performer") {
    return `Break down what makes '${opp.segment}' outperform on ${opp.metric} — what patterns distinguish them?`;
  }
  if (opp.opportunity_type === "undermonetized") {
    return `Analyze '${opp.segment}' — why is monetization low despite high volume? Show the user journey.`;
  }
  if (opp.opportunity_type === "growth_potential") {
    return `Show me more detail on '${opp.segment}' — what would it take to scale this channel?`;
  }
  return `Investigate ${opp.metric} for segment '${opp.segment}' to understand this opportunity`;
}

export function OpportunityCard({
  opportunities,
  onDrillDown,
}: OpportunityCardProps) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  const handleToggle = useCallback((idx: number) => {
    setExpandedIdx((prev) => (prev === idx ? null : idx));
  }, []);

  if (!opportunities || opportunities.length === 0) return null;

  return (
    <div className="mt-2 space-y-1.5">
      <div className="flex items-center gap-1.5 text-[11px] text-text-tertiary font-medium uppercase tracking-wider">
        <span>💰</span>
        Opportunities ({opportunities.length})
      </div>
      {opportunities.map((opp, idx) => {
        const cfg = TYPE_CONFIG[opp.opportunity_type] || DEFAULT_TYPE;
        const isExpanded = expandedIdx === idx;
        const confidencePct = Math.round(opp.confidence * 100);

        return (
          <div
            key={idx}
            className={`rounded-xl border ${cfg.border} ${cfg.bg} transition-all`}
          >
            <button
              onClick={() => handleToggle(idx)}
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] w-full text-left"
            >
              <span className="shrink-0">{cfg.icon}</span>
              <span
                className={`font-medium truncate ${cfg.color}`}
                title={opp.title}
              >
                {opp.title}
              </span>
              <span className="ml-auto flex items-center gap-1 shrink-0">
                <span
                  className={`text-[10px] px-1 py-0.5 rounded ${
                    opp.gap_pct > 0
                      ? "bg-success-muted text-success"
                      : "bg-error-muted text-error"
                  }`}
                >
                  {opp.gap_pct > 0 ? "+" : ""}
                  {opp.gap_pct}%
                </span>
                <span className="text-[10px] text-text-tertiary tabular-nums">
                  {confidencePct}%
                </span>
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
                  {opp.description}
                </p>

                {opp.estimated_impact && (
                  <div className="flex gap-1.5 text-[11px]">
                    <span className="text-text-tertiary shrink-0">
                      📊 Impact:
                    </span>
                    <span className="text-text-primary">
                      {opp.estimated_impact}
                    </span>
                  </div>
                )}

                {opp.suggested_action && (
                  <div className="flex gap-1.5 text-[11px]">
                    <span className="text-text-tertiary shrink-0">
                      → Action:
                    </span>
                    <span className="text-success">
                      {opp.suggested_action}
                    </span>
                  </div>
                )}

                {opp.evidence.length > 0 && (
                  <div className="flex flex-wrap gap-1 pt-0.5">
                    {opp.evidence.map((e, i) => (
                      <span
                        key={i}
                        className="text-[10px] px-1.5 py-0.5 bg-surface-2 rounded text-text-tertiary"
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
                      onDrillDown(drillQuestion(opp));
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
