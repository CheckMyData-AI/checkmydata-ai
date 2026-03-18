"use client";

import { useId } from "react";

interface TooltipProps {
  label: string;
  position?: "top" | "bottom" | "right";
  children: React.ReactNode;
}

export function Tooltip({ label, position = "bottom", children }: TooltipProps) {
  const id = useId();

  if (!label) return <>{children}</>;

  const positionClasses =
    position === "top"
      ? "bottom-full left-1/2 -translate-x-1/2 mb-1.5"
      : position === "right"
        ? "left-full top-1/2 -translate-y-1/2 ml-1.5"
        : "top-full left-1/2 -translate-x-1/2 mt-1.5";

  return (
    <span className="relative inline-flex group/tooltip" aria-describedby={id}>
      {children}
      <span
        id={id}
        role="tooltip"
        className={`
          pointer-events-none absolute z-50 whitespace-nowrap
          px-2 py-1 rounded-md text-[10px] font-medium leading-none
          bg-surface-3 text-text-primary border border-border-default
          opacity-0 scale-95
          group-hover/tooltip:opacity-100 group-hover/tooltip:scale-100
          group-focus-within/tooltip:opacity-100 group-focus-within/tooltip:scale-100
          transition-all duration-150 delay-200
          ${positionClasses}
        `}
      >
        {label}
      </span>
    </span>
  );
}
