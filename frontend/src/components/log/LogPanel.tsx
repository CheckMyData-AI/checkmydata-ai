"use client";

import { memo, useEffect, useRef } from "react";
import { useLogStore, type LogEntry } from "@/stores/log-store";
import { Icon } from "@/components/ui/Icon";

const PIPELINE_COLORS: Record<string, string> = {
  index_repo: "text-purple-400",
  db_index: "text-emerald-400",
  code_db_sync: "text-teal-400",
  orchestrator: "text-orange-400",
  query: "text-cyan-400",
  agent: "text-amber-400",
  system: "text-text-muted",
};

const STATUS_COLORS: Record<string, string> = {
  started: "text-info",
  completed: "text-success",
  failed: "text-error",
  skipped: "text-text-muted",
};

const PIPELINE_LABELS: Record<string, string> = {
  index_repo: "INDEX",
  db_index: "DB-IDX",
  code_db_sync: "SYNC",
  orchestrator: "ORCH",
  query: "QUERY",
  agent: "AGENT",
  system: "SYS",
};

const STEP_LABELS: Record<string, string> = {
  pipeline_start: "Starting",
  pipeline_resume: "Resuming",
  pipeline_end: "Done",
  no_changes: "No Changes",
  resolve_ssh_key: "SSH Key",
  clone_or_pull: "Git Clone/Pull",
  detect_changes: "Detect Changes",
  cleanup_deleted: "Cleanup Deleted",
  project_profile: "Project Profile",
  analyze_files: "Analyze Files",
  cross_file_analysis: "Cross-File Analysis",
  enrich_docs: "Enrich Docs",
  generate_docs: "Generate Docs",
  record_index: "Record Index",
  resolve_connection: "Connection",
  introspect_schema: "Introspect Schema",
  fetch_samples: "Fetch Samples",
  load_context: "Load Context",
  validate_tables: "LLM Analysis",
  store_results: "Store Results",
  generate_summary: "Generate Summary",
  load_code_knowledge: "Load Code Knowledge",
  load_db_index: "Load DB Index",
  match_tables: "Match Tables",
  analyze_sync: "Analyze Code-DB",
  store_sync: "Store Sync",
  generate_sync_summary: "Generate Summary",
  load_rules: "Rules",
  rag_context: "RAG Context",
  build_query: "Build Query",
  safety_check: "Safety Check",
  pre_validate: "Schema Validation",
  explain_check: "EXPLAIN Check",
  execute_query: "Execute Query",
  post_validate: "Result Validation",
  error_classify: "Error Analysis",
  query_repair: "Query Repair",
  interpret_results: "Interpret",
  render_viz: "Visualize",
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

const LogLine = memo(function LogLine({ entry }: { entry: LogEntry }) {
  const pipelineColor =
    PIPELINE_COLORS[entry.pipeline] || PIPELINE_COLORS.system;
  const statusColor = STATUS_COLORS[entry.status] || "text-text-tertiary";
  const label =
    PIPELINE_LABELS[entry.pipeline] || entry.pipeline.toUpperCase();
  const elapsed = formatElapsed(entry.elapsedMs);

  return (
    <div className="flex gap-1.5 leading-5 hover:bg-surface-2/50 px-2">
      <span className="text-text-muted shrink-0">
        {formatTime(entry.timestamp)}
      </span>
      <span
        className={`shrink-0 font-semibold w-12 text-right ${pipelineColor}`}
      >
        {label}
      </span>
      <span className="text-text-muted shrink-0">{STEP_LABELS[entry.step] || entry.step}:</span>
      <span className={`shrink-0 ${statusColor}`}>{entry.status}</span>
      {entry.detail && (
        <span className={`truncate ${
          entry.status === "failed"
            ? "text-error/70"
            : entry.step === "pipeline_start" || entry.step === "pipeline_end"
              ? "text-text-secondary"
              : "text-text-muted"
        }`}>{entry.detail}</span>
      )}
      {elapsed && (
        <span className="text-text-muted ml-auto shrink-0 tabular-nums">
          {elapsed}
        </span>
      )}
    </div>
  );
});

export function LogToggleButton() {
  const { isOpen, isConnected, unreadCount, toggle } = useLogStore();

  if (isOpen) return null;

  return (
    <button
      onClick={toggle}
      className="flex items-center gap-2 px-3 py-3 bg-surface-2 border border-border-subtle rounded-lg text-xs text-text-tertiary hover:text-text-primary hover:bg-surface-3 transition-colors whitespace-nowrap"
    >
      <span
        className={`w-2 h-2 rounded-full ${isConnected ? "bg-success" : "bg-surface-3"}`}
      />
      <Icon name="activity" size={12} />
      Activity Log
      {unreadCount > 0 && (
        <span className="bg-accent text-white text-[10px] px-1.5 py-0.5 rounded-full min-w-[18px] text-center">
          {unreadCount > 99 ? "99+" : unreadCount}
        </span>
      )}
    </button>
  );
}

export function LogPanel() {
  const { entries, isOpen, isConnected, toggle, clear, resetUnread } =
    useLogStore();
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
    wasAtBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 32;
  };

  if (!isOpen) return null;

  return (
    <div
      className="border-t border-border-subtle bg-surface-0 flex flex-col"
      style={{ height: 200 }}
    >
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border-subtle bg-surface-1/50 shrink-0">
        <span
          className={`w-2 h-2 rounded-full ${isConnected ? "bg-success" : "bg-surface-3"}`}
        />
        <Icon name="activity" size={12} className="text-text-tertiary" />
        <span className="text-[11px] font-medium text-text-tertiary uppercase tracking-wider">
          Activity Log
        </span>
        <span className="text-[10px] text-text-muted tabular-nums">
          {entries.length} entries
        </span>
        <div className="ml-auto flex items-center gap-1">
          <button
            onClick={clear}
            className="text-[10px] text-text-muted hover:text-text-secondary transition-colors px-1.5 py-0.5"
            title="Clear log"
          >
            Clear
          </button>
          <button
            onClick={toggle}
            className="text-[10px] text-text-muted hover:text-text-secondary transition-colors px-1.5 py-0.5"
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
          <div className="flex items-center justify-center h-full text-text-muted text-xs">
            Waiting for events...
          </div>
        ) : (
          entries.map((entry) => <LogLine key={entry.id} entry={entry} />)
        )}
      </div>
    </div>
  );
}
