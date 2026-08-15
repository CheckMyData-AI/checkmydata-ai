"use client";

import { cn } from "@/lib/utils";

export interface BadgeProps {
  children: React.ReactNode;
  tone?: "neutral" | "accent" | "success" | "warning" | "error" | "info";
  className?: string;
}

/* The pack's chip is a transparent fill with a 1px border of its own colour
   at 30% alpha. A status tone keeps the word in --ink and lets the border
   carry the hue: four of the five semantic colours sit under 4.5:1 on the
   light field, so the word is the message and the colour reinforces it. */
const TONE: Record<NonNullable<BadgeProps["tone"]>, string> = {
  neutral: "text-text-secondary border-border-strong",
  accent: "text-accent border-accent-line",
  success: "text-ink border-ok/40 bg-ok-weak",
  warning: "text-ink border-warn/40 bg-warn-weak",
  error: "text-ink border-danger/40 bg-danger-weak",
  info: "text-ink border-info/40 bg-info-weak",
};

export function Badge({ children, tone = "neutral", className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-control border px-2 py-0.5 font-mono text-kicker tracking-kicker uppercase",
        TONE[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
