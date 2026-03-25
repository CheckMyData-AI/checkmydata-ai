"use client";

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <div className={`flex justify-center py-3 ${className}`} role="status" aria-live="polite">
      <div className="w-4 h-4 border-2 border-surface-3 border-t-text-secondary rounded-full animate-spin" />
      <span className="sr-only">Loading…</span>
    </div>
  );
}
