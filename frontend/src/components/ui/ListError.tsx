"use client";

interface ListErrorProps {
  message: string;
  onRetry: () => void;
  className?: string;
}

/**
 * Inline "it broke" state for list/panel load failures (audit M5): keeps a
 * failed fetch visually distinct from a legitimately empty list and offers a
 * retry. Used by Logs tabs, schedules, learnings, and the connections list.
 */
export function ListError({ message, onRetry, className }: ListErrorProps) {
  return (
    <div
      className={
        className ??
        "p-6 text-center text-xs text-error flex flex-col items-center gap-2"
      }
    >
      <span>{message}</span>
      <button onClick={onRetry} className="underline hover:no-underline">
        Retry
      </button>
    </div>
  );
}
