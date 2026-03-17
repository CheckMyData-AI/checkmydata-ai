"use client";

import { useEffect, useRef } from "react";
import { useLogStore, type LogEntry } from "@/stores/log-store";

const PIPELINE_COLORS: Record<string, string> = {
  index_repo: "text-purple-400",
  query: "text-cyan-400",
  agent: "text-amber-400",
  system: "text-zinc-500",
};

const STATUS_COLORS: Record<string, string> = {
  started: "text-blue-400",
  completed: "text-emerald-400",
  failed: "text-red-400",
  skipped: "text-zinc-500",
};

const PIPELINE_LABELS: Record<string, string> = {
  index_repo: "INDEX",
  query: "QUERY",
  agent: "AGENT",
  system: "SYS",
};

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
  });
}

function formatElapsed(ms: number | null): string {
  if (ms == null) return "";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

function LogLine({ entry }: { entry: LogEntry }) {
  const pipelineColor = PIPELINE_COLORS[entry.pipeline] || PIPELINE_COLORS.system;
  const statusColor = STATUS_COLORS[entry.status] || "text-zinc-400";
  const label = PIPELINE_LABELS[entry.pipeline] || entry.pipeline.toUpperCase();
  const elapsed = formatElapsed(entry.elapsedMs);

  return (
    <div className="flex gap-1.5 leading-5 hover:bg-zinc-800/50 px-2">
      <span className="text-zinc-600 shrink-0">{formatTime(entry.timestamp)}</span>
      <span className={`shrink-0 font-semibold w-12 text-right ${pipelineColor}`}>
        {label}
      </span>
      <span className="text-zinc-500 shrink-0">{entry.step}:</span>
      <span className={`shrink-0 ${statusColor}`}>{entry.status}</span>
      {entry.detail && (
        <span className="text-zinc-500 truncate">{entry.detail}</span>
      )}
      {elapsed && (
        <span className="text-zinc-600 ml-auto shrink-0 tabular-nums">{elapsed}</span>
      )}
    </div>
  );
}

export function LogPanel() {
  const { entries, isOpen, isConnected, unreadCount, toggle, clear, resetUnread } = useLogStore();
  const scrollRef = useRef<HTMLDivElement>(null);
  const wasAtBottomRef = useRef(true);

  useEffect(() => {
    if (!isOpen) return;
    resetUnread();
  }, [isOpen, resetUnread]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !isOpen) return;
    if (wasAtBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [entries.length, isOpen]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    wasAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
  };

  if (!isOpen) {
    return (
      <button
        onClick={toggle}
        className="fixed bottom-4 right-4 z-50 flex items-center gap-2 px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-xs text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700 transition-colors shadow-lg"
      >
        <span className={`w-2 h-2 rounded-full ${isConnected ? "bg-emerald-400" : "bg-zinc-600"}`} />
        Activity Log
        {unreadCount > 0 && (
          <span className="bg-blue-500 text-white text-[10px] px-1.5 py-0.5 rounded-full min-w-[18px] text-center">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>
    );
  }

  return (
    <div className="border-t border-zinc-800 bg-zinc-950 flex flex-col" style={{ height: 200 }}>
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-zinc-800 bg-zinc-900/50 shrink-0">
        <span className={`w-2 h-2 rounded-full ${isConnected ? "bg-emerald-400" : "bg-zinc-600"}`} />
        <span className="text-[11px] font-medium text-zinc-400 uppercase tracking-wider">
          Activity Log
        </span>
        <span className="text-[10px] text-zinc-600 tabular-nums">
          {entries.length} entries
        </span>
        <div className="ml-auto flex items-center gap-1">
          <button
            onClick={clear}
            className="text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors px-1.5 py-0.5"
            title="Clear log"
          >
            Clear
          </button>
          <button
            onClick={toggle}
            className="text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors px-1.5 py-0.5"
            title="Close log panel"
          >
            Close
          </button>
        </div>
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto overflow-x-hidden font-mono text-[11px] py-1"
      >
        {entries.length === 0 ? (
          <div className="flex items-center justify-center h-full text-zinc-600 text-xs">
            Waiting for events...
          </div>
        ) : (
          entries.map((entry) => <LogLine key={entry.id} entry={entry} />)
        )}
      </div>
    </div>
  );
}
