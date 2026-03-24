"use client";

import type { ToolCallEvent } from "@/stores/app-store";

const TOOL_LABELS: Record<string, string> = {
  "tool:execute_query": "Running SQL query",
  "tool:search_knowledge": "Searching knowledge base",
  "tool:get_schema_info": "Checking database schema",
  "tool:get_custom_rules": "Loading custom rules",
  llm_call: "Thinking",
  "orchestrator:llm_call": "Thinking",
  "orchestrator:sql_agent": "SQL Agent working",
  "orchestrator:knowledge_agent": "Knowledge Agent working",
  "orchestrator:viz": "Choosing visualization",
  "orchestrator:manage_rules": "Managing rules",
  "orchestrator:process_data": "Enriching data",
  "sql:llm_call": "SQL Agent thinking",
  "sql:get_schema": "Checking schema",
  "sql:load_rules": "Loading rules",
  "sql:get_db_index": "Loading DB index",
  "sql:get_sync": "Loading sync context",
  "sql:get_query_ctx": "Building query context",
  "sql:learnings": "Loading learnings",
  "sql:record_learn": "Recording learning",
  "knowledge:llm_call": "Knowledge Agent thinking",
};

const AGENT_LABELS: Record<string, string> = {
  orchestrator: "Orchestrator",
  sql: "SQL Agent",
  knowledge: "Knowledge Agent",
  viz: "Visualization Agent",
};

interface ToolCallIndicatorProps {
  events: ToolCallEvent[];
}

function resolveLabel(event: ToolCallEvent): string {
  const step = event.step ?? "";
  const agentPrefix = step.split(":")[0];
  const agentLabel = AGENT_LABELS[agentPrefix];
  if (TOOL_LABELS[step]) return TOOL_LABELS[step];
  if (agentLabel) return `${agentLabel}: ${event.detail ?? "working"}`;
  return event.detail ?? "Working";
}

export function ToolCallIndicator({ events }: ToolCallIndicatorProps) {
  if (events.length === 0) return null;

  const recentStarted = events
    .filter((e) => e.status === "started")
    .slice(-5);

  const latest = events[events.length - 1];
  const isActive = latest.status === "started";

  if (recentStarted.length <= 1) {
    const label = resolveLabel(latest);
    return (
      <div className="flex items-center gap-2 text-xs text-zinc-400 min-w-0">
        {isActive && (
          <span className="relative flex h-2 w-2 shrink-0">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-blue-500" />
          </span>
        )}
        <span className="truncate">{label}…</span>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {recentStarted.map((ev, idx) => {
        const label = resolveLabel(ev);
        const isCurrent = idx === recentStarted.length - 1;
        return (
          <div key={`${ev.step}-${idx}`} className="flex items-center gap-2 text-xs">
            {isCurrent ? (
              <span className="relative flex h-2 w-2 shrink-0">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-blue-500" />
              </span>
            ) : (
              <span className="flex h-2 w-2 shrink-0 rounded-full bg-zinc-600" />
            )}
            <span className={isCurrent ? "text-zinc-300" : "text-zinc-500"}>
              {label}{isCurrent ? "…" : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}
