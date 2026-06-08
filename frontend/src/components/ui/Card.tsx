"use client";

import { cn } from "@/lib/utils";

export interface CardProps {
  children: React.ReactNode;
  className?: string;
  padding?: "sm" | "md";
}

export function Card({ children, className, padding = "md" }: CardProps) {
  return (
    <div
      className={cn(
        "bg-surface-1 rounded-xl border border-border-subtle",
        padding === "sm" ? "p-3" : "p-5",
        className,
      )}
    >
      {children}
    </div>
  );
}
