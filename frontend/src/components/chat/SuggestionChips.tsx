"use client";

import type { QuerySuggestion } from "@/lib/api";

interface SuggestionChipsProps {
  suggestions: QuerySuggestion[];
  loading?: boolean;
  onSelect: (text: string) => void;
}

function SkeletonChips() {
  return (
    <div className="flex gap-2 animate-pulse">
      {[1, 2, 3].map((i) => (
        <div
          key={i}
          className="h-7 rounded-full bg-surface-2/60 border border-border-default/30"
          style={{ width: `${80 + i * 24}px` }}
        />
      ))}
    </div>
  );
}

export function SuggestionChips({ suggestions, loading, onSelect }: SuggestionChipsProps) {
  if (loading) {
    return (
      <div className="px-6 pb-2">
        <SkeletonChips />
      </div>
    );
  }

  if (!suggestions.length) return null;

  return (
    <div className="px-6 pb-2 animate-in fade-in slide-in-from-bottom-2 duration-300">
      <div className="relative">
      <div className="flex items-center gap-2 overflow-x-auto scrollbar-none pb-1" role="group" aria-label="Suggested questions">
        <svg
          className="w-3.5 h-3.5 text-warning/70 shrink-0"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
          />
        </svg>
        {suggestions.map((s, i) => (
          <button
            key={i}
            onClick={() => onSelect(s.text)}
            title={s.text}
            className="shrink-0 max-w-[280px] truncate px-3 py-1.5 text-xs text-text-primary bg-surface-2/60 border border-border-default/40 rounded-full hover:bg-surface-3/60 hover:border-border-default/50 hover:text-text-primary transition-all duration-150 cursor-pointer"
          >
            {s.text.length > 60 ? s.text.slice(0, 57) + "..." : s.text}
          </button>
        ))}
      </div>
      <div className="pointer-events-none absolute right-0 top-0 bottom-0 w-8 bg-gradient-to-l from-surface-0 to-transparent" />
      </div>
    </div>
  );
}

interface FollowupChipsProps {
  followups: string[];
  onSelect: (text: string) => void;
}

export function FollowupChips({ followups, onSelect }: FollowupChipsProps) {
  if (!followups.length) return null;

  return (
    <div className="mt-2 flex flex-wrap gap-1.5 animate-in fade-in duration-200" role="group" aria-label="Follow-up questions">
      {followups.map((text, i) => (
        <button
          key={i}
          onClick={() => onSelect(text)}
          className="px-2.5 py-1 text-[11px] text-text-secondary bg-surface-1/50 border border-border-default/30 rounded-full hover:bg-surface-2/80 hover:text-text-primary hover:border-border-default/40 transition-all duration-150 cursor-pointer"
        >
          {text}
        </button>
      ))}
    </div>
  );
}
