"use client";

import { useReasoningStore, type ReasoningStep } from "@/stores/reasoning-store";

const STEP_ICONS: Record<string, string> = {
  "orchestrator:llm_call": "brain",
  "orchestrator:sql_agent": "database",
  "orchestrator:knowledge_agent": "book",
  "orchestrator:viz": "chart",
  "orchestrator:manage_rules": "scroll",
  "orchestrator:planning": "map",
  "sql:llm_call": "brain",
  "sql:get_schema": "table",
  "sql:get_db_index": "list",
  "sql:get_query_ctx": "search",
  "sql:learnings": "lightbulb",
  "knowledge:llm_call": "brain",
};

function getIcon(step: string): string {
  if (STEP_ICONS[step]) return STEP_ICONS[step];
  if (step.includes("llm")) return "brain";
  if (step.includes("sql") || step.includes("query")) return "database";
  if (step.includes("tool")) return "wrench";
  return "circle";
}

function IconSvg({ icon, className }: { icon: string; className?: string }) {
  const cls = className ?? "h-3.5 w-3.5";
  switch (icon) {
    case "brain":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 0 1-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 0 1 4.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0 1 12 15a9.065 9.065 0 0 0-6.23.693L5 14.5m14.8.8 1.402 1.402c1.232 1.232.65 3.318-1.067 3.611l-.772.129a9 9 0 0 1-9.726 0l-.772-.13c-1.718-.292-2.3-2.378-1.067-3.61L5 14.5" />
        </svg>
      );
    case "database":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
        </svg>
      );
    case "lightbulb":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 18v-5.25m0 0a6.01 6.01 0 0 0 1.5-.189m-1.5.189a6.01 6.01 0 0 1-1.5-.189m3.75 7.478a12.06 12.06 0 0 1-4.5 0m3.75 2.383a14.406 14.406 0 0 1-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 1 0-7.517 0c.85.493 1.509 1.333 1.509 2.316V18" />
        </svg>
      );
    default:
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <circle cx="12" cy="12" r="3" />
        </svg>
      );
  }
}

function StepRow({ step, isLast }: { step: ReasoningStep; isLast: boolean }) {
  const icon = getIcon(step.step);
  const label = step.detail || step.step.replace(/:/g, " ").trim() || "Step";
  const isCompleted = step.status === "completed";
  const isFailed = step.status === "failed";
  const isStarted = step.status === "started";

  return (
    <div className="flex items-start gap-2 relative">
      <div className="flex flex-col items-center shrink-0">
        <div
          className={`rounded-full p-1 ${
            isFailed
              ? "bg-error/10 text-error"
              : isCompleted
                ? "bg-success/10 text-success"
                : isStarted
                  ? "bg-accent/10 text-accent"
                  : "bg-surface-3 text-text-muted"
          }`}
        >
          <IconSvg icon={icon} />
        </div>
        {!isLast && <div className="w-px h-full min-h-3 bg-border" />}
      </div>
      <div className="flex-1 min-w-0 pb-3">
        <div className="flex items-center gap-2">
          <span
            className={`text-[11px] font-medium truncate ${
              isFailed ? "text-error" : isStarted ? "text-text-primary" : "text-text-secondary"
            }`}
          >
            {label}
          </span>
          {step.elapsed_ms != null && step.elapsed_ms > 0 && (
            <span className="text-[10px] text-text-muted shrink-0">
              {step.elapsed_ms < 1000
                ? `${step.elapsed_ms}ms`
                : `${(step.elapsed_ms / 1000).toFixed(1)}s`}
            </span>
          )}
        </div>
        {step.agent && (
          <span className="text-[10px] text-text-tertiary">{step.agent}</span>
        )}
      </div>
    </div>
  );
}

export function ReasoningPanel() {
  const panelOpen = useReasoningStore((s) => s.panelOpen);
  const activeMessageId = useReasoningStore((s) => s.activeMessageId);
  const traces = useReasoningStore((s) => s.traces);
  const closePanel = useReasoningStore((s) => s.closePanel);

  if (!panelOpen || !activeMessageId) return null;

  const trace = traces[activeMessageId];
  if (!trace) {
    return (
      <aside className="hidden md:flex flex-col w-80 border-l border-border bg-surface-0 animate-in slide-in-from-right-2 duration-200">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <h3 className="text-sm font-semibold text-text-primary">Agent Reasoning</h3>
          <button onClick={closePanel} className="text-text-muted hover:text-text-primary transition-colors" aria-label="Close">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="flex-1 flex items-center justify-center p-4">
          <p className="text-sm text-text-muted">No reasoning data available for this message.</p>
        </div>
      </aside>
    );
  }

  const plan = trace.planSummary;
  const elapsed = trace.endTime
    ? `${((trace.endTime - trace.startTime) / 1000).toFixed(1)}s`
    : null;

  const significantSteps = trace.steps.filter(
    (s) => s.step !== "thinking" && s.step !== "token" && s.step !== "plan_summary",
  );

  return (
    <aside className="hidden md:flex flex-col w-80 border-l border-border bg-surface-0 animate-in slide-in-from-right-2 duration-200 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-text-primary">Agent Reasoning</h3>
          {elapsed && (
            <span className="text-[10px] text-text-muted font-mono bg-surface-2 px-1.5 py-0.5 rounded">
              {elapsed}
            </span>
          )}
        </div>
        <button onClick={closePanel} className="text-text-muted hover:text-text-primary transition-colors" aria-label="Close">
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin px-4 py-3 space-y-4">
        {plan && (
          <section>
            <h4 className="text-[11px] font-semibold text-text-muted uppercase tracking-wider mb-2">
              Plan
            </h4>
            <div className="space-y-1.5 text-[11px]">
              {plan.tables.length > 0 && (
                <div>
                  <span className="text-text-muted">Tables: </span>
                  <span className="text-text-secondary font-mono">{plan.tables.join(", ")}</span>
                </div>
              )}
              <div>
                <span className="text-text-muted">Strategy: </span>
                <span className="text-text-secondary">
                  {plan.strategy === "pipeline" ? "Multi-stage pipeline" : "Single query"}
                </span>
              </div>
              {plan.rules_applied.length > 0 && (
                <div>
                  <span className="text-text-muted">Rules: </span>
                  <span className="text-text-secondary">{plan.rules_applied.join(", ")}</span>
                </div>
              )}
              {plan.learnings_applied.length > 0 && (
                <div>
                  <span className="text-text-muted">Learnings: </span>
                  <span className="text-text-secondary">{plan.learnings_applied.join(", ")}</span>
                </div>
              )}
              {plan.has_warnings && (
                <div className="text-warning">Table resolution warnings present</div>
              )}
            </div>
          </section>
        )}

        {trace.thinkingLog.length > 0 && (
          <section>
            <h4 className="text-[11px] font-semibold text-text-muted uppercase tracking-wider mb-2">
              Thinking ({trace.thinkingLog.length})
            </h4>
            <div className="space-y-0.5 max-h-40 overflow-y-auto scrollbar-thin">
              {trace.thinkingLog.map((line, idx) => (
                <div key={idx} className="text-[10px] text-text-tertiary font-mono leading-tight break-words">
                  {line}
                </div>
              ))}
            </div>
          </section>
        )}

        {significantSteps.length > 0 && (
          <section>
            <h4 className="text-[11px] font-semibold text-text-muted uppercase tracking-wider mb-2">
              Steps ({significantSteps.length})
            </h4>
            <div>
              {significantSteps.map((step, idx) => (
                <StepRow
                  key={`${step.step}-${idx}`}
                  step={step}
                  isLast={idx === significantSteps.length - 1}
                />
              ))}
            </div>
          </section>
        )}
      </div>
    </aside>
  );
}
