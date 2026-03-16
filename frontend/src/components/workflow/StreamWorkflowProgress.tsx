"use client";

import { useMemo } from "react";
import type { WorkflowEvent } from "@/lib/sse";

interface StepState {
  name: string;
  status: "started" | "completed" | "failed" | "skipped" | "pending";
  detail: string;
  elapsed_ms: number | null;
  count: number;
}

const STEP_LABELS: Record<string, string> = {
  introspect_schema: "Schema",
  load_rules: "Rules",
  build_query: "Build Query",
  safety_check: "Safety Check",
  pre_validate: "Schema Validation",
  explain_check: "EXPLAIN Check",
  execute_query: "Execute Query",
  post_validate: "Result Validation",
  error_classify: "Error Analysis",
  query_repair: "Query Repair",
  interpret_results: "Interpret",
};

function StepIcon({ status }: { status: StepState["status"] }) {
  switch (status) {
    case "started":
      return (
        <span className="w-3.5 h-3.5 rounded-full border-2 border-blue-400 border-t-transparent animate-spin inline-block" />
      );
    case "completed":
      return (
        <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      );
    case "failed":
      return (
        <svg className="w-3.5 h-3.5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      );
    default:
      return <span className="w-3.5 h-3.5 rounded-full bg-zinc-700 inline-block" />;
  }
}

interface StreamWorkflowProgressProps {
  events: WorkflowEvent[];
  compact?: boolean;
}

export function StreamWorkflowProgress({ events, compact = false }: StreamWorkflowProgressProps) {
  const steps = useMemo(() => {
    const map = new Map<string, StepState>();
    for (const ev of events) {
      if (ev.step === "pipeline_start" || ev.step === "pipeline_end") continue;
      const existing = map.get(ev.step);
      const prevCount = existing?.count ?? 0;
      map.set(ev.step, {
        name: ev.step,
        status: ev.status as StepState["status"],
        detail: ev.detail,
        elapsed_ms: ev.elapsed_ms,
        count: ev.status === "started" ? prevCount + 1 : (existing ? existing.count : 1),
      });
    }
    return Array.from(map.values());
  }, [events]);

  if (steps.length === 0) return null;

  if (compact) {
    const current = steps.findLast((s) => s.status === "started") || steps[steps.length - 1];
    return (
      <div className="flex items-center gap-2 text-xs text-zinc-400">
        <StepIcon status={current.status} />
        <span>{STEP_LABELS[current.name] || current.name}</span>
        {current.detail && <span className="text-zinc-600 truncate max-w-40">{current.detail}</span>}
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {steps.map((step) => (
        <div key={step.name} className="flex items-center gap-2 text-xs">
          <StepIcon status={step.status} />
          <span className={step.status === "failed" ? "text-red-400" : step.status === "started" ? "text-blue-300" : "text-zinc-300"}>
            {STEP_LABELS[step.name] || step.name}
            {step.count > 1 && <span className="ml-1 text-zinc-500">x{step.count}</span>}
          </span>
          {step.elapsed_ms != null && step.status !== "started" && (
            <span className="text-zinc-600 ml-auto tabular-nums whitespace-nowrap">
              {step.elapsed_ms >= 1000
                ? `${(step.elapsed_ms / 1000).toFixed(1)}s`
                : `${Math.round(step.elapsed_ms)}ms`}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
