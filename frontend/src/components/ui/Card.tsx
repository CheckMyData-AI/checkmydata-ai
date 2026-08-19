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
        // Elevation is the hairline: 1px at 12% ink, radius 15, no shadow.
        "bg-panel rounded-card border border-border",
        padding === "sm" ? "p-3" : "p-5",
        className,
      )}
    >
      {children}
    </div>
  );
}
