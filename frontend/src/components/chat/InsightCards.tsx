"use client";

import { useState, useCallback } from "react";

export interface Insight {
  type: string;
  title: string;
  description: string;
  confidence: number;
  column?: string;
}

interface InsightCardsProps {
  insights: Insight[];
  onDrillDown?: (question: string) => void;
}

const TYPE_CONFIG: Record<string, { color: string; bg: string; border: string; icon: JSX.Element }> = {
  trend_up: {
    color: "text-blue-400",
    bg: "bg-blue-950/30",
    border: "border-blue-900/40",
    icon: (
      <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M7 17l4.586-4.586a2 2 0 012.828 0L17 15m0 0V9m0 6h-6" />
      </svg>
    ),
  },
  trend_down: {
    color: "text-blue-400",
    bg: "bg-blue-950/30",
    border: "border-blue-900/40",
    icon: (
      <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M17 7l-4.586 4.586a2 2 0 01-2.828 0L7 9m0 0v6m0-6h6" />
      </svg>
    ),
  },
  outlier: {
    color: "text-amber-400",
    bg: "bg-amber-950/30",
    border: "border-amber-900/40",
    icon: (
      <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
      </svg>
    ),
  },
  concentration: {
    color: "text-purple-400",
    bg: "bg-purple-950/30",
    border: "border-purple-900/40",
    icon: (
      <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M18 20V10M12 20V4M6 20v-6" />
      </svg>
    ),
  },
  summary: {
    color: "text-zinc-400",
    bg: "bg-zinc-800/50",
    border: "border-zinc-700/50",
    icon: (
      <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
  },
};

const DEFAULT_CONFIG = {
  color: "text-zinc-400",
  bg: "bg-zinc-800/50",
  border: "border-zinc-700/50",
  icon: (
    <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  ),
};

function drillDownQuestion(insight: Insight): string {
  const col = insight.column || "the main metric";
  if (insight.type.startsWith("trend_")) {
    return `Show me the detailed breakdown of ${col} over time to understand this trend`;
  }
  if (insight.type === "outlier") {
    return `Show me the rows where ${col} has outlier values and explain what makes them unusual`;
  }
  if (insight.type === "concentration") {
    return `Show me the top entries by ${col} and their individual share of the total`;
  }
  return `Tell me more about ${col}`;
}

export function InsightCards({ insights, onDrillDown }: InsightCardsProps) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  const handleToggle = useCallback((idx: number) => {
    setExpandedIdx((prev) => (prev === idx ? null : idx));
  }, []);

  if (!insights || insights.length === 0) return null;

  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {insights.map((insight, idx) => {
        const cfg = TYPE_CONFIG[insight.type] || DEFAULT_CONFIG;
        const isExpanded = expandedIdx === idx;

        return (
          <div key={idx} className={`rounded-lg border ${cfg.border} ${cfg.bg} transition-all`}>
            <button
              onClick={() => handleToggle(idx)}
              className={`flex items-center gap-1.5 px-2 py-1 text-[11px] ${cfg.color} w-full text-left`}
            >
              {cfg.icon}
              <span className="font-medium truncate max-w-[200px]">{insight.title}</span>
            </button>
            {isExpanded && (
              <div className="px-2 pb-1.5 space-y-1">
                <p className="text-[11px] text-zinc-400 leading-relaxed">
                  {insight.description}
                </p>
                {onDrillDown && insight.type !== "summary" && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDrillDown(drillDownQuestion(insight));
                      setExpandedIdx(null);
                    }}
                    className={`text-[10px] px-1.5 py-0.5 rounded border ${cfg.border} ${cfg.color} hover:brightness-125 transition-all`}
                  >
                    Drill down
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
