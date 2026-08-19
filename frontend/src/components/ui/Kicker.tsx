"use client";

import { cn } from "@/lib/utils";

/**
 * The `ledger` pack's recurring motif: 10px monospace, uppercase, +0.1em, in the
 * accent. On the pack's reference this is where the accent lives — of eleven
 * accent-coloured elements on that page, five are this label and none is a
 * button.
 *
 * Use it above a section title, above a figure, or as a runnable example query
 * in an empty state. Two accent kickers stacked is one too many: the second
 * takes `tone="muted"`.
 */
export interface KickerProps extends React.HTMLAttributes<HTMLParagraphElement> {
  tone?: "accent" | "muted";
}

export function Kicker({ tone = "accent", className, ...props }: KickerProps) {
  return (
    <p
      className={cn(
        "font-mono text-kicker tracking-kicker uppercase",
        tone === "accent" ? "text-accent" : "text-text-tertiary",
        className,
      )}
      {...props}
    />
  );
}
