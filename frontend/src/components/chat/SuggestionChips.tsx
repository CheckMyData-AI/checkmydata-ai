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
          className="h-7 rounded-full bg-zinc-800/60 border border-zinc-700/30"
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
      <div className="flex items-center gap-2 overflow-x-auto scrollbar-none pb-1">
        <svg
          className="w-3.5 h-3.5 text-amber-400/70 shrink-0"
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
            className="shrink-0 max-w-[280px] truncate px-3 py-1.5 text-xs text-zinc-300 bg-zinc-800/60 border border-zinc-700/40 rounded-full hover:bg-zinc-700/60 hover:border-zinc-600/50 hover:text-zinc-100 transition-all duration-150 cursor-pointer"
          >
            {s.text.length > 60 ? s.text.slice(0, 57) + "..." : s.text}
          </button>
        ))}
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
    <div className="mt-2 flex flex-wrap gap-1.5 animate-in fade-in duration-200">
      {followups.map((text, i) => (
        <button
          key={i}
          onClick={() => onSelect(text)}
          className="px-2.5 py-1 text-[11px] text-zinc-400 bg-zinc-900/50 border border-zinc-700/30 rounded-full hover:bg-zinc-800/80 hover:text-zinc-200 hover:border-zinc-600/40 transition-all duration-150 cursor-pointer"
        >
          {text}
        </button>
      ))}
    </div>
  );
}
