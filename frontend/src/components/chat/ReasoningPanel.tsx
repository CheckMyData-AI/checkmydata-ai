"use client";

import { useRef } from "react";
import { useReasoningStore, type ReasoningStep } from "@/stores/reasoning-store";
import { Icon } from "@/components/ui/Icon";
import { useDialogA11y } from "@/hooks/useDialogA11y";
import { useMobileLayout } from "@/hooks/useMobileLayout";

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

function getIconName(step: string): "activity" | "database" | "book-open" | "bar-chart-2" | "file-text" | "layout" | "layers" | "search" | "zap" | "settings" | "circle" {
  const mapped = STEP_ICONS[step];
  if (mapped === "brain") return "activity";
  if (mapped === "book") return "book-open";
  if (mapped === "chart") return "bar-chart-2";
  if (mapped === "scroll") return "file-text";
  if (mapped === "map") return "layout";
  if (mapped === "table") return "layers";
  if (mapped === "list") return "layers";
  if (mapped === "lightbulb") return "zap";
  if (mapped === "database") return "database";
  if (mapped === "search") return "search";
  if (step.includes("llm")) return "activity";
  if (step.includes("sql") || step.includes("query")) return "database";
  if (step.includes("tool")) return "settings";
  return "circle";
}

function StepRow({
  step,
  isLast,
  index = 0,
}: {
  step: ReasoningStep;
  isLast: boolean;
  index?: number;
}) {
  const icon = getIconName(step.step);
  const label = step.detail || step.step.replace(/:/g, " ").trim() || "Step";
  const isCompleted = step.status === "completed";
  const isFailed = step.status === "failed";
  const isStarted = step.status === "started";

  return (
    <div
      className="animate-slide-in-left flex items-start gap-2 relative"
      style={{ animationDelay: `${Math.min(index, 12) * 35}ms`, animationFillMode: "both" }}
    >
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
          <Icon name={icon} className="h-3.5 w-3.5" />
        </div>
        {!isLast && <div className="w-px flex-1 min-h-4 bg-border-subtle mt-1" />}
      </div>
      <div className="flex-1 min-w-0 pb-3">
        <p className="text-xs text-text-primary leading-snug">{label}</p>
        {step.agent && (
          <span className="text-xs text-text-tertiary">{step.agent}</span>
        )}
      </div>
    </div>
  );
}

function ReasoningPanelBody({ onClose }: { onClose: () => void }) {
  const activeMessageId = useReasoningStore((s) => s.activeMessageId);
  const traces = useReasoningStore((s) => s.traces);

  if (!activeMessageId) return null;

  const trace = traces[activeMessageId];
  if (!trace) {
    return (
      <>
        <div className="flex items-center justify-between px-4 py-3 border-b border-border-subtle shrink-0">
          <h3 className="text-sm font-semibold text-text-primary">Agent Reasoning</h3>
          <button
            type="button"
            onClick={onClose}
            className="text-text-muted hover:text-text-primary transition-colors p-1"
            aria-label="Close reasoning panel"
          >
            <Icon name="x" className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 flex items-center justify-center p-4">
          <p className="text-sm text-text-muted">No reasoning data available for this message.</p>
        </div>
      </>
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
    <>
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-subtle shrink-0">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-text-primary">Agent Reasoning</h3>
          {elapsed && (
            <span className="text-xs text-text-muted font-mono bg-surface-2 px-1.5 py-0.5 rounded">
              {elapsed}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-text-muted hover:text-text-primary transition-colors p-1"
          aria-label="Close reasoning panel"
        >
          <Icon name="x" className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin px-4 py-3 space-y-4">
        {plan && (
          <section>
            <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
              Plan
            </h4>
            <div className="space-y-1.5 text-xs">
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
            <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
              Thinking ({trace.thinkingLog.length})
            </h4>
            <div className="space-y-0.5 max-h-40 overflow-y-auto scrollbar-thin">
              {trace.thinkingLog.map((line, idx) => (
                <div key={idx} className="text-xs text-text-tertiary font-mono leading-tight break-words">
                  {line}
                </div>
              ))}
            </div>
          </section>
        )}

        {significantSteps.length > 0 && (
          <section>
            <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
              Steps ({significantSteps.length})
            </h4>
            <div>
              {significantSteps.map((step, idx) => (
                <StepRow
                  key={`${step.step}-${idx}`}
                  step={step}
                  index={idx}
                  isLast={idx === significantSteps.length - 1}
                />
              ))}
            </div>
          </section>
        )}
      </div>
    </>
  );
}

export function ReasoningPanel() {
  const panelOpen = useReasoningStore((s) => s.panelOpen);
  const activeMessageId = useReasoningStore((s) => s.activeMessageId);
  const closePanel = useReasoningStore((s) => s.closePanel);
  const isMobile = useMobileLayout();
  const mobileRef = useRef<HTMLDivElement>(null);

  useDialogA11y({
    open: isMobile && panelOpen && !!activeMessageId,
    onClose: closePanel,
    panelRef: mobileRef,
  });

  if (!panelOpen || !activeMessageId) return null;

  if (isMobile) {
    return (
      <>
        <button
          type="button"
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
          aria-label="Close reasoning panel"
          onClick={closePanel}
        />
        <div
          ref={mobileRef}
          role="dialog"
          aria-modal="true"
          aria-label="Agent reasoning"
          className="fixed inset-x-0 bottom-0 z-50 flex flex-col max-h-[85vh] rounded-t-xl border border-border-subtle bg-surface-0 checkpoint-reveal md:hidden"
        >
          <ReasoningPanelBody onClose={closePanel} />
        </div>
      </>
    );
  }

  return (
    <aside className="hidden md:flex flex-col w-80 border-l border-border-subtle bg-surface-0 animate-in slide-in-from-right-2 duration-200 overflow-hidden">
      <ReasoningPanelBody onClose={closePanel} />
    </aside>
  );
}
