"use client";

import { cn } from "@/lib/utils";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean;
  hint?: string;
}

/**
 * The pack's field: 38px tall on the data plane, a hairline border, radius 10,
 * and focus as a 2px accent ring at 2px offset — an outline rather than a
 * `ring`, because the pack's focus contract is the one place this design
 * overrules its reference, which answers focus by swapping a border colour and
 * so leaves a borderless control with no focus state at all.
 */
export const inputBaseCls =
  "w-full h-[38px] px-3 bg-panel-2 text-text-primary rounded-control text-body border border-border " +
  "transition-colors duration-(--dur) ease-(--ease) placeholder-text-muted " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring focus:outline-none";

export function Input({ className, invalid, hint, "aria-label": ariaLabel, ...props }: InputProps) {
  return (
    <div className="w-full">
      <input
        className={cn(
          inputBaseCls,
          invalid && "border-danger focus-visible:outline-danger",
          className,
        )}
        aria-invalid={invalid || undefined}
        aria-label={ariaLabel}
        {...props}
      />
      {hint ? (
        <p className="mt-1 px-1 text-meta text-text-tertiary">{hint}</p>
      ) : null}
    </div>
  );
}
