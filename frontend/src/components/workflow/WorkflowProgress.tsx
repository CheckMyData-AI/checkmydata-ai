"use client";

import { useEffect, useState, useRef } from "react";
import { subscribeToWorkflow, type WorkflowEvent } from "@/lib/sse";

interface StepState {
  name: string;
  status: "started" | "completed" | "failed" | "skipped" | "pending";
  detail: string;
  elapsed_ms: number | null;
  count: number;
}

const STEP_LABELS: Record<string, string> = {
  pipeline_start: "Starting",
  resolve_ssh_key: "SSH Key",
  clone_or_pull: "Git Clone/Pull",
  detect_changes: "Detect Changes",
  analyze_files: "Analyze Files",
  generate_docs: "Generate Docs",
  chunk_and_store: "Store Vectors",
  record_index: "Record Index",
  pipeline_end: "Done",
  resolve_connection: "Connection",
  introspect_schema: "Schema",
  load_rules: "Rules",
  rag_context: "RAG Context",
  build_query: "Build Query",
  safety_check: "Safety Check",
  pre_validate: "Schema Validation",
  explain_check: "EXPLAIN Check",
  execute_query: "Execute Query",
  post_validate: "Result Validation",
  error_classify: "Error Analysis",
  query_repair: "Query Repair",
  interpret_results: "Interpret",
  render_viz: "Visualize",
};

const RETRY_STEPS = new Set([
  "pre_validate",
  "explain_check",
  "post_validate",
  "error_classify",
  "query_repair",
]);

function StepIcon({ status, isRetry }: { status: StepState["status"]; isRetry?: boolean }) {
  if (isRetry && status === "started") {
    return (
      <span className="w-4 h-4 rounded-full border-2 border-amber-400 border-t-transparent animate-spin inline-block" />
    );
  }
  switch (status) {
    case "started":
      return (
        <span className="w-4 h-4 rounded-full border-2 border-blue-400 border-t-transparent animate-spin inline-block" />
      );
    case "completed":
      return (
        <svg className="w-4 h-4 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      );
    case "failed":
      return (
        <svg className="w-4 h-4 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      );
    default:
      return <span className="w-4 h-4 rounded-full bg-zinc-700 inline-block" />;
  }
}

interface WorkflowProgressProps {
  workflowId: string | null;
  compact?: boolean;
  onComplete?: (status: "completed" | "failed", detail: string) => void;
}

export function WorkflowProgress({ workflowId, compact = false, onComplete }: WorkflowProgressProps) {
  const [steps, setSteps] = useState<StepState[]>([]);
  const [pipelineStatus, setPipelineStatus] = useState<"running" | "completed" | "failed">("running");
  const unsubRef = useRef<(() => void) | null>(null);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  useEffect(() => {
    if (!workflowId) return;

    setSteps([]);
    setPipelineStatus("running");

    const unsub = subscribeToWorkflow(workflowId, (event: WorkflowEvent) => {
      if (event.step === "pipeline_end") {
        const finalStatus = event.status === "failed" ? "failed" : "completed";
        setPipelineStatus(finalStatus);
        onCompleteRef.current?.(finalStatus as "completed" | "failed", event.detail);
        return;
      }
      if (event.step === "pipeline_start") return;

      setSteps((prev) => {
        const existing = prev.findIndex((s) => s.name === event.step);
        const prevCount = existing >= 0 ? prev[existing].count : 0;
        const updated: StepState = {
          name: event.step,
          status: event.status,
          detail: event.detail,
          elapsed_ms: event.elapsed_ms,
          count: event.status === "started" ? prevCount + 1 : (existing >= 0 ? prev[existing].count : 1),
        };

        if (existing >= 0) {
          const copy = [...prev];
          copy[existing] = updated;
          return copy;
        }
        return [...prev, updated];
      });
    });

    unsubRef.current = unsub;
    return () => {
      unsub();
      unsubRef.current = null;
    };
  }, [workflowId]);

  if (!workflowId || steps.length === 0) return null;

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
      {steps.map((step) => {
        const isRetry = RETRY_STEPS.has(step.name);
        const statusColor =
          step.status === "started"
            ? isRetry ? "text-amber-300" : "text-blue-300"
            : step.status === "failed"
              ? "text-red-400"
              : "text-zinc-300";
        return (
          <div key={step.name} className="flex items-center gap-2 text-xs">
            <StepIcon status={step.status} isRetry={isRetry && step.count > 1} />
            <span className={statusColor}>
              {STEP_LABELS[step.name] || step.name}
              {step.count > 1 && (
                <span className="ml-1 text-zinc-500">x{step.count}</span>
              )}
            </span>
            {step.detail && (
              <span className={`truncate max-w-48 ${step.status === "failed" ? "text-red-500/70" : "text-zinc-600"}`}>
                {step.detail}
              </span>
            )}
            {step.elapsed_ms != null && step.status !== "started" && (
              <span className="text-zinc-600 ml-auto tabular-nums whitespace-nowrap">
                {step.elapsed_ms >= 1000
                  ? `${(step.elapsed_ms / 1000).toFixed(1)}s`
                  : `${Math.round(step.elapsed_ms)}ms`}
              </span>
            )}
          </div>
        );
      })}
      {pipelineStatus === "running" && steps.every((s) => s.status !== "started") && (
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <span className="w-4 h-4 rounded-full border-2 border-zinc-600 border-t-transparent animate-spin inline-block" />
          <span>Processing...</span>
        </div>
      )}
    </div>
  );
}
