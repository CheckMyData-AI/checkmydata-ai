"use client";

import { cn } from "@/lib/utils";

export interface ProgressBarProps {
  value: number;
  max: number;
  tone?: "accent" | "success" | "error";
  label?: string;
  className?: string;
}

const FILL: Record<NonNullable<ProgressBarProps["tone"]>, string> = {
  accent: "bg-accent",
  success: "bg-success",
  error: "bg-error",
};

export function ProgressBar({
  value,
  max,
  tone = "accent",
  label,
  className,
}: ProgressBarProps) {
  const safeMax = max > 0 ? max : 1;
  const clamped = Math.min(Math.max(value, 0), safeMax);
  const ratio = clamped / safeMax;

  return (
    <div className={cn("w-full", className)}>
      {label ? (
        <span className="sr-only">{label}</span>
      ) : null}
      <div
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={safeMax}
        aria-label={label ?? "Progress"}
        className="h-1.5 w-full rounded-full bg-surface-2 overflow-hidden"
      >
        <div
          className={cn("h-full pipeline-progress-fill", FILL[tone])}
          style={{ transform: `scaleX(${ratio})` }}
        />
      </div>
    </div>
  );
}
