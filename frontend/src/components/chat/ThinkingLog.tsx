"use client";

import { useEffect, useRef } from "react";

interface ThinkingLogProps {
  entries: string[];
}

export function ThinkingLog({ entries }: ThinkingLogProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries.length]);

  if (entries.length === 0) return null;

  return (
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
  );
}
