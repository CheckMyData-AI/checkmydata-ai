"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/components/ui/Icon";

export interface PlanSummaryData {
  tables: string[];
  strategy: string;
  rules_applied: string[];
  learnings_applied: string[];
  has_warnings: boolean;
}

interface PlanSummaryCardProps {
  data: PlanSummaryData;
  collapsed?: boolean;
}

export function PlanSummaryCard({ data, collapsed }: PlanSummaryCardProps) {
  const [isOpen, setIsOpen] = useState(true);

  useEffect(() => {
    if (collapsed) setIsOpen(false);
  }, [collapsed]);

  if (!data.tables.length && !data.rules_applied.length && !data.learnings_applied.length) {
    return null;
  }

  const strategyLabel =
    data.strategy === "pipeline" ? "Multi-stage pipeline" : "Single query";

  return (
    <div className="rounded-lg border border-border-subtle bg-surface-1 px-3 py-2 text-xs font-mono animate-in fade-in slide-in-from-top-1 duration-300">
      <button
        onClick={() => setIsOpen((o) => !o)}
        className="flex items-center gap-1.5 w-full text-left text-text-secondary hover:text-text-primary transition-colors"
        aria-expanded={isOpen}
      >
        <Icon
          name="chevron-right"
          className={`h-3 w-3 shrink-0 transition-transform ${isOpen ? "rotate-90" : ""}`}
        />
        <span className="font-semibold text-text-primary">Plan</span>
        <span className="text-text-muted">
          {strategyLabel}
          {data.tables.length > 0 && ` · ${data.tables.length} table${data.tables.length !== 1 ? "s" : ""}`}
        </span>
        {data.has_warnings && (
          <span className="ml-auto text-warning text-xs">has warnings</span>
        )}
      </button>

      {isOpen && (
        <div className="mt-2 space-y-1.5 pl-4 border-l border-border-subtle ml-1">
          {data.tables.length > 0 && (
            <div className="flex items-start gap-1">
              <span className="text-text-muted shrink-0">Tables:</span>
              <span className="text-text-secondary break-words">
                {data.tables.join(", ")}
              </span>
            </div>
          )}
          {data.rules_applied.length > 0 && (
            <div className="flex items-start gap-1">
              <span className="text-text-muted shrink-0">Rules:</span>
              <span className="text-text-secondary break-words">
                {data.rules_applied.join(", ")}
              </span>
            </div>
          )}
          {data.learnings_applied.length > 0 && (
            <div className="flex items-start gap-1">
              <span className="text-text-muted shrink-0">Learnings:</span>
              <span className="text-text-secondary break-words">
                {data.learnings_applied.join(", ")}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
