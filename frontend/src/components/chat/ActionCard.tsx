"use client";

import React, { useState, useCallback } from "react";

export interface ActionData {
  action_type: string;
  title: string;
  description: string;
  what_to_do: string;
  expected_impact: string;
  impact_metric: string;
  impact_estimate_pct: number;
  priority: string;
  effort: string;
  confidence: number;
  prerequisites: string[];
  risks: string[];
  source_insight_type: string;
  source_insight_title: string;
}

interface ActionCardProps {
  actions: ActionData[];
  onDrillDown?: (question: string) => void;
}

const PRIORITY_CONFIG: Record<
  string,
  { icon: string; color: string; bg: string; border: string }
> = {
  critical: {
    icon: "🔴",
    color: "text-error",
    bg: "bg-error-muted",
    border: "border-border-default",
  },
  high: {
    icon: "🟠",
    color: "text-warning",
    bg: "bg-warning-muted",
    border: "border-border-default",
  },
  medium: {
    icon: "🟡",
    color: "text-warning",
    bg: "bg-warning-muted",
    border: "border-border-default",
  },
  low: {
    icon: "🔵",
    color: "text-accent",
    bg: "bg-accent-muted",
    border: "border-border-default",
  },
};

const DEFAULT_PRIORITY = {
  icon: "⚪",
  color: "text-text-secondary",
  bg: "bg-surface-2",
  border: "border-border-default",
};

const EFFORT_BADGE: Record<string, string> = {
  low: "bg-success-muted text-success",
  medium: "bg-warning-muted text-warning",
  high: "bg-error-muted text-error",
};

export function ActionCard({ actions, onDrillDown }: ActionCardProps) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  const handleToggle = useCallback((idx: number) => {
    setExpandedIdx((prev) => (prev === idx ? null : idx));
  }, []);

  if (!actions || actions.length === 0) return null;

  return (
    <div className="mt-2 space-y-1.5">
      <div className="flex items-center gap-1.5 text-[11px] text-text-tertiary font-medium uppercase tracking-wider">
        <span>🎯</span>
        Recommended Actions ({actions.length})
      </div>
      {actions.map((action, idx) => {
        const cfg = PRIORITY_CONFIG[action.priority] || DEFAULT_PRIORITY;
        const isExpanded = expandedIdx === idx;
        const effortClass = EFFORT_BADGE[action.effort] || EFFORT_BADGE.medium;

        return (
          <div
            key={idx}
            className={`rounded-xl border ${cfg.border} ${cfg.bg} transition-all`}
          >
            <button
              onClick={() => handleToggle(idx)}
              aria-expanded={isExpanded}
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] w-full text-left"
            >
              <span className="shrink-0">{cfg.icon}</span>
              <span className={`font-medium truncate ${cfg.color}`} title={action.title}>
                {action.title}
              </span>
              <span className="ml-auto flex items-center gap-1 shrink-0">
                {action.impact_estimate_pct > 0 && (
                  <span className="text-[10px] px-1 py-0.5 rounded bg-success-muted text-success">
                    +{action.impact_estimate_pct}%
                  </span>
                )}
                <span className={`text-[10px] px-1 py-0.5 rounded ${effortClass}`}>
                  {action.effort}
                </span>
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
              <div className="px-2.5 pb-2 space-y-1.5 border-t border-border-subtle">
                {action.what_to_do && (
                  <div className="text-[11px] text-text-primary leading-relaxed pt-1.5">
                    📋 {action.what_to_do}
                  </div>
                )}

                {action.expected_impact && (
                  <div className="flex gap-1.5 text-[11px]">
                    <span className="text-text-tertiary shrink-0">📊 Expected:</span>
                    <span className="text-success">{action.expected_impact}</span>
                  </div>
                )}

                {action.prerequisites.length > 0 && (
                  <div className="text-[11px]">
                    <span className="text-text-tertiary">Prerequisites: </span>
                    <span className="text-text-secondary">
                      {action.prerequisites.join(" • ")}
                    </span>
                  </div>
                )}

                {action.risks.length > 0 && (
                  <div className="text-[11px]">
                    <span className="text-text-tertiary">Risks: </span>
                    <span className="text-warning/80">
                      {action.risks.join(" • ")}
                    </span>
                  </div>
                )}

                {action.source_insight_title && (
                  <div className="text-[10px] text-text-muted">
                    From: {action.source_insight_type} — {action.source_insight_title}
                  </div>
                )}

                {onDrillDown && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDrillDown(
                        `Help me implement this action: ${action.what_to_do}`
                      );
                      setExpandedIdx(null);
                    }}
                    className={`text-[10px] px-1.5 py-0.5 rounded border ${cfg.border} ${cfg.color} hover:brightness-125 transition-all`}
                  >
                    Help me implement this
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
