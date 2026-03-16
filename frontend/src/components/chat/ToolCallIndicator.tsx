"use client";

import type { ToolCallEvent } from "@/stores/app-store";

const TOOL_LABELS: Record<string, string> = {
  "tool:execute_query": "Running SQL query",
  "tool:search_knowledge": "Searching knowledge base",
  "tool:get_schema_info": "Checking database schema",
  "tool:get_custom_rules": "Loading custom rules",
  llm_call: "Thinking",
};

interface ToolCallIndicatorProps {
  events: ToolCallEvent[];
}

export function ToolCallIndicator({ events }: ToolCallIndicatorProps) {
  if (events.length === 0) return null;

  const latest = events[events.length - 1];
  const label = TOOL_LABELS[latest.step] ?? latest.detail ?? "Working";
  const isActive = latest.status === "started";

  return (
    <div className="flex items-center gap-2 text-xs text-zinc-400">
      {isActive && (
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-blue-500" />
        </span>
      )}
      <span>{label}…</span>
    </div>
  );
}
