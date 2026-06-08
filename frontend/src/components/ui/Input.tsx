"use client";

import { cn } from "@/lib/utils";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean;
  hint?: string;
}

export const inputBaseCls =
  "w-full px-3.5 py-2.5 bg-surface-1 text-text-primary rounded-lg text-sm border border-border-subtle focus:border-accent focus:ring-1 focus:ring-accent focus:outline-none transition-colors placeholder-text-muted";

export function Input({ className, invalid, hint, "aria-label": ariaLabel, ...props }: InputProps) {
  return (
    <div className="w-full">
      <input
        className={cn(
          inputBaseCls,
          invalid && "border-error focus:border-error focus:ring-error/30",
          className,
        )}
        aria-invalid={invalid || undefined}
        aria-label={ariaLabel}
        {...props}
      />
      {hint ? (
        <p className="text-xs text-text-muted mt-1 px-1">{hint}</p>
      ) : null}
    </div>
  );
}
