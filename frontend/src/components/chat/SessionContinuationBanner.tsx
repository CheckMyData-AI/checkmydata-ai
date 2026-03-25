"use client";

import { useState } from "react";

interface SessionContinuationBannerProps {
  messageCount: number;
  summaryPreview?: string;
  topics?: string[];
}

export function SessionContinuationBanner({
  messageCount,
  summaryPreview,
  topics,
}: SessionContinuationBannerProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="flex flex-col items-center gap-1 py-3 select-none">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2 text-xs text-text-2 hover:text-text-1 transition-colors group cursor-pointer"
      >
        <span className="h-px w-12 bg-border group-hover:bg-text-2 transition-colors" />
        <span>
          Conversation continued ({messageCount} messages summarized)
        </span>
        <span className="h-px w-12 bg-border group-hover:bg-text-2 transition-colors" />
        <svg
          className={`w-3 h-3 transition-transform ${expanded ? "rotate-180" : ""}`}
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        >
          <path d="M3 5l3 3 3-3" />
        </svg>
      </button>

      {expanded && (
        <div className="mt-1.5 max-w-md text-xs text-text-2 bg-surface-2 rounded-lg px-3 py-2 border border-border">
          {summaryPreview && <p className="mb-1">{summaryPreview}</p>}
          {topics && topics.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1">
              {topics.map((t) => (
                <span
                  key={t}
                  className="px-1.5 py-0.5 bg-surface-3 rounded text-[10px] text-text-2"
                >
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
