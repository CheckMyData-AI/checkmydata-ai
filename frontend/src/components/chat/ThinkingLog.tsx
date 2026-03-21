"use client";

import { useEffect, useRef, useMemo } from "react";

interface ThinkingLogProps {
  entries: string[];
  startTime?: number;
}

export function ThinkingLog({ entries, startTime }: ThinkingLogProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries.length]);

  const elapsed = useMemo(() => {
    if (!startTime) return null;
    const secs = Math.round((Date.now() - startTime) / 1000);
    if (secs < 2) return null;
    return `${secs}s`;
  }, [startTime, entries.length]);

  if (entries.length === 0) return null;

  return (
    <div className="space-y-1">
      {elapsed && (
        <div className="text-[10px] text-zinc-600 font-mono text-right">
          {elapsed} elapsed
        </div>
      )}
      <div
        ref={scrollRef}
        className="max-h-[120px] overflow-y-auto space-y-0.5 scrollbar-thin"
        data-testid="thinking-log"
      >
        {entries.map((entry, idx) => {
          const isLatest = idx === entries.length - 1;
          return (
            <div
              key={idx}
              className={`flex items-start gap-1.5 text-[11px] leading-tight font-mono animate-in fade-in duration-200 ${
                isLatest ? "text-zinc-300" : "text-zinc-500"
              }`}
            >
              {isLatest ? (
                <span className="mt-[3px] shrink-0 relative flex h-1.5 w-1.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-75" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-blue-500" />
                </span>
              ) : (
                <span className="mt-[3px] shrink-0 h-1.5 w-1.5 rounded-full bg-zinc-600" />
              )}
              <span className="break-words min-w-0">{entry}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
