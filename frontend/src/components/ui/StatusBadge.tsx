"use client";

import { Icon } from "@/components/ui/Icon";
import type { PipelineStageStatus } from "@/components/chat/pipeline-types";
import { cn } from "@/lib/utils";

export interface StatusBadgeProps {
  status: PipelineStageStatus;
  size?: "sm" | "md";
  className?: string;
}

const LABELS: Record<PipelineStageStatus, string> = {
  pending: "Stage pending",
  running: "Stage running",
  passed: "Stage passed",
  failed: "Stage failed",
  checkpoint: "Stage waiting for review",
  skipped: "Stage skipped",
  validating: "Validating data",
};

const COLORS: Record<PipelineStageStatus, string> = {
  pending: "text-text-tertiary",
  running: "text-accent",
  passed: "text-success",
  failed: "text-error",
  checkpoint: "text-warning",
  skipped: "text-text-muted",
  validating: "text-info",
};

const ICONS = {
  pending: "circle" as const,
  running: "loader" as const,
  passed: "check" as const,
  failed: "x" as const,
  checkpoint: "pause" as const,
  skipped: "minus" as const,
  validating: "loader" as const,
};

export function StatusBadge({ status, size = "md", className }: StatusBadgeProps) {
  const iconSize = size === "sm" ? 12 : 14;
  const iconName = ICONS[status];

  return (
    <span
      role="img"
      aria-label={LABELS[status]}
      className={cn("inline-flex shrink-0 items-center justify-center", COLORS[status], className)}
    >
      <Icon
        name={iconName}
        size={iconSize}
        className={cn(status === "running" || status === "validating" ? "animate-spin" : undefined)}
        aria-hidden
      />
    </span>
  );
}
