"use client";

import { motion, useReducedMotion } from "motion/react";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Badge } from "@/components/ui/Badge";
import { Icon } from "@/components/ui/Icon";
import type { PipelineStage } from "@/components/chat/pipeline-types";
import { SPRING } from "@/lib/motion/tokens";
import { cn } from "@/lib/utils";

export interface StageRowProps {
  stage: PipelineStage;
  index: number;
  isCurrent: boolean;
  expanded: boolean;
  onToggle?: () => void;
  showConnector?: boolean;
  className?: string;
}

const STATUS_BG: Record<string, string> = {
  pending: "bg-surface-2 border-border-subtle",
  running: "bg-accent-muted border-border-default",
  passed: "bg-success-muted/50 border-border-subtle",
  failed: "bg-error-muted border-border-default",
  checkpoint: "bg-warning-muted border-border-default",
  skipped: "bg-surface-2/50 border-border-subtle",
  validating: "bg-info-muted border-border-default",
};

function formatToolLabel(tool: string): string {
  return tool.replace(/_/g, " ");
}

export function StageRow({
  stage,
  index,
  isCurrent,
  expanded,
  onToggle,
  showConnector = true,
  className,
}: StageRowProps) {
  const compact = !expanded && !isCurrent;
  const muted = stage.status === "pending" || stage.status === "skipped";
  const reduced = useReducedMotion();

  return (
    <motion.div
      layout="position"
      initial={reduced ? false : { opacity: 0, y: 10, scale: 0.99 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={reduced ? { duration: 0 } : SPRING.chip}
      className={cn(
        "flex gap-2 rounded-lg border px-3 py-2 text-sm",
        STATUS_BG[stage.status] ?? "bg-surface-2",
        isCurrent && stage.status === "running" && "stage-active-glow",
        stage.status === "failed" && "stage-failed-shake",
        className,
      )}
    >
      <div className="flex flex-col items-center pt-0.5 shrink-0">
        <StatusBadge status={stage.status} size="sm" />
        {showConnector ? <div className="w-px h-3 bg-surface-3 mt-1" aria-hidden /> : null}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-start gap-2">
          <button
            type="button"
            className={cn(
              "flex-1 min-w-0 text-left",
              onToggle && "cursor-pointer hover:opacity-90",
              !onToggle && "cursor-default",
            )}
            onClick={onToggle}
            aria-expanded={expanded}
            aria-label={`Stage ${index + 1}: ${stage.description}`}
          >
            <span
              className={cn(
                "font-medium block",
                compact ? "truncate" : "line-clamp-2",
                muted ? "text-text-tertiary" : "text-text-primary",
              )}
              title={stage.description}
            >
              {stage.description}
            </span>
          </button>
          {!compact && stage.tool ? (
            <Badge tone="neutral" className="shrink-0 capitalize">
              {formatToolLabel(stage.tool)}
            </Badge>
          ) : null}
        </div>

        {stage.status === "validating" && stage.dataGateDetail ? (
          <p className="text-xs text-info mt-1">{stage.dataGateDetail}</p>
        ) : null}

        {stage.status === "passed" && (stage.rowCount !== undefined || stage.columns?.length) ? (
          <div className="text-xs text-text-tertiary mt-0.5">
            {stage.rowCount !== undefined ? <span>{stage.rowCount} rows</span> : null}
            {stage.columns?.length ? (
              <span className="ml-2">
                ({stage.columns.slice(0, 4).join(", ")}
                {stage.columns.length > 4 ? ` +${stage.columns.length - 4}` : ""})
              </span>
            ) : null}
          </div>
        ) : null}

        {stage.status === "failed" && stage.error ? (
          <p className="text-xs text-error/90 mt-0.5 line-clamp-2" title={stage.error}>
            {stage.error}
          </p>
        ) : null}

        {stage.warnings && stage.warnings.length > 0 ? (
          <div className="flex items-start gap-1 text-xs text-warning mt-0.5">
            <Icon name="alert-triangle" size={12} className="shrink-0 mt-0.5" aria-hidden />
            <span className="line-clamp-2">{stage.warnings.join("; ")}</span>
          </div>
        ) : null}
      </div>
    </motion.div>
  );
}
