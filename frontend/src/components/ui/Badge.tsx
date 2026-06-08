"use client";

import { cn } from "@/lib/utils";

export interface BadgeProps {
  children: React.ReactNode;
  tone?: "neutral" | "accent" | "success" | "warning" | "error" | "info";
  className?: string;
}

const TONE: Record<NonNullable<BadgeProps["tone"]>, string> = {
  neutral: "bg-surface-2 text-text-secondary border-border-subtle",
  accent: "bg-accent-muted text-accent border-accent/30",
  success: "bg-success-muted text-success border-success/30",
  warning: "bg-warning-muted text-warning border-warning/30",
  error: "bg-error-muted text-error border-error/30",
  info: "bg-info-muted text-info border-info/30",
};

export function Badge({ children, tone = "neutral", className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs font-medium",
        TONE[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
