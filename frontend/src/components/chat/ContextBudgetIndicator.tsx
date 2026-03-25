"use client";

import { useState } from "react";
import type { CostEstimateBreakdown } from "@/lib/api";

interface ContextBudgetIndicatorProps {
  breakdown: CostEstimateBreakdown;
}

const SEGMENTS: { key: keyof CostEstimateBreakdown; label: string; color: string }[] = [
  { key: "schema_context", label: "Schema", color: "bg-accent" },
  { key: "rules", label: "Rules", color: "bg-accent" },
  { key: "learnings", label: "Learnings", color: "bg-warning" },
  { key: "overview", label: "Overview", color: "bg-info" },
  { key: "history_budget_remaining", label: "History remaining", color: "bg-surface-3" },
];

export function ContextBudgetIndicator({ breakdown }: ContextBudgetIndicatorProps) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  const total = SEGMENTS.reduce((sum, seg) => sum + (breakdown[seg.key] || 0), 0);
  if (total === 0) return null;

  const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

  return (
    <div className="relative">
      <div className="flex h-1 rounded-full overflow-hidden bg-surface-2">
        {SEGMENTS.map((seg, i) => {
          const value = breakdown[seg.key] || 0;
          if (value === 0) return null;
          const pct = (value / total) * 100;
          return (
            <div
              key={seg.key}
              className={`${seg.color} transition-opacity ${hoveredIdx !== null && hoveredIdx !== i ? "opacity-40" : ""}`}
              style={{ width: `${pct}%` }}
              onMouseEnter={() => setHoveredIdx(i)}
              onMouseLeave={() => setHoveredIdx(null)}
            />
          );
        })}
      </div>

      {hoveredIdx !== null && (
        <div className="absolute bottom-full left-0 mb-1 z-50 bg-surface-2 border border-border-default rounded px-2 py-1 text-[10px] text-text-primary shadow-lg whitespace-nowrap">
          {SEGMENTS[hoveredIdx].label}: {fmt(breakdown[SEGMENTS[hoveredIdx].key] || 0)} tokens
        </div>
      )}
    </div>
  );
}
