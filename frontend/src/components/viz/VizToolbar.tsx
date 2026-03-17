"use client";

import { VIZ_TYPES, type VizTypeKey } from "@/lib/viz-utils";

interface VizToolbarProps {
  activeType: string;
  onTypeChange: (type: VizTypeKey) => void;
  disabled?: boolean;
  loading?: boolean;
}

function VizIcon({ type }: { type: string }) {
  switch (type) {
    case "table":
      return (
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M3 14h18M3 6h18M3 18h18M8 6v12M16 6v12" />
        </svg>
      );
    case "bar":
      return (
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6m6 0h6m-6 0V9a2 2 0 012-2h2a2 2 0 012 2v10m6 0v-4a2 2 0 00-2-2h-2a2 2 0 00-2 2v4" />
        </svg>
      );
    case "line":
      return (
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 17l6-6 4 4 8-8" />
        </svg>
      );
    case "pie":
      return (
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M11 3.055A9.001 9.001 0 1020.945 13H11V3.055z" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M20.488 9H15V3.512A9.025 9.025 0 0120.488 9z" />
        </svg>
      );
    case "scatter":
      return (
        <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
          <circle cx="6" cy="14" r="1.5" />
          <circle cx="10" cy="8" r="1.5" />
          <circle cx="14" cy="12" r="1.5" />
          <circle cx="18" cy="6" r="1.5" />
          <circle cx="8" cy="18" r="1.5" />
          <circle cx="16" cy="16" r="1.5" />
        </svg>
      );
    default:
      return null;
  }
}

export function VizToolbar({ activeType, onTypeChange, disabled, loading }: VizToolbarProps) {
  return (
    <div className="flex items-center gap-0.5 p-0.5 bg-zinc-900/60 rounded-lg w-fit">
      {VIZ_TYPES.map((vt) => {
        const isActive = activeType === vt.key;
        return (
          <button
            key={vt.key}
            onClick={() => onTypeChange(vt.key)}
            disabled={disabled || loading}
            title={vt.label}
            className={`flex items-center gap-1 px-2 py-1 rounded-md text-[11px] transition-colors ${
              isActive
                ? "bg-blue-600 text-white"
                : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"
            } ${disabled ? "opacity-40 cursor-not-allowed" : ""}`}
          >
            <VizIcon type={vt.icon} />
            <span className="hidden sm:inline">{vt.label}</span>
          </button>
        );
      })}
      {loading && (
        <span className="ml-1 w-3 h-3 border-2 border-zinc-600 border-t-blue-400 rounded-full animate-spin" />
      )}
    </div>
  );
}
