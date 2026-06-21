"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type SyncHistoryRun } from "@/lib/api";
import { Icon } from "@/components/ui/Icon";
import { Tooltip } from "@/components/ui/Tooltip";

interface SyncHistoryPanelProps {
  projectId: string;
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function connectionCounts(run: SyncHistoryRun): string | null {
  if (!run.steps) return null;
  const connections = run.steps["connections"];
  if (!Array.isArray(connections)) return null;
  const total = connections.length;
  const succeeded = connections.filter(
    (c) =>
      typeof c === "object" &&
      c !== null &&
      (c as Record<string, unknown>)["status"] === "success",
  ).length;
  return `${succeeded}/${total} connections`;
}

const STATUS_ICON: Record<SyncHistoryRun["status"], Parameters<typeof Icon>[0]["name"]> = {
  success: "check",
  partial: "alert-triangle",
  failed: "alert-triangle",
  skipped: "minus",
};

const STATUS_COLOR: Record<SyncHistoryRun["status"], string> = {
  success: "text-success",
  partial: "text-warning",
  failed: "text-error",
  skipped: "text-text-tertiary",
};

function RunRow({ run, isLatest }: { run: SyncHistoryRun; isLatest: boolean }) {
  const [expanded, setExpanded] = useState(isLatest);
  const counts = connectionCounts(run);
  const ago = timeAgo(run.created_at);
  const statusColor = STATUS_COLOR[run.status];
  const iconName = STATUS_ICON[run.status];

  const summary = [run.status, ago, counts].filter(Boolean).join(" · ");

  return (
    <li className="rounded-md border border-border-subtle bg-surface-0/50">
      <div className="flex items-center gap-2 px-2.5 py-2">
        <Icon name={iconName} size={12} className={`shrink-0 ${statusColor}`} />
        <span className={`text-xs flex-1 min-w-0 truncate ${statusColor}`}>{summary}</span>
        {run.duration_seconds !== null && (
          <span className="text-[10px] text-text-tertiary shrink-0">
            {run.duration_seconds}s
          </span>
        )}
        <Tooltip label={expanded ? "Collapse" : "Expand"}>
          <button
            onClick={() => setExpanded((v) => !v)}
            aria-label={expanded ? "Collapse run detail" : "Expand run detail"}
            aria-expanded={expanded}
            className="shrink-0 text-text-tertiary hover:text-text-primary transition-colors"
          >
            <Icon name={expanded ? "chevron-up" : "chevron-down"} size={12} />
          </button>
        </Tooltip>
      </div>

      {expanded && (
        <div className="px-2.5 pb-2 space-y-1 border-t border-border-subtle/50 pt-2">
          <div className="flex items-center gap-1.5 text-[10px] text-text-tertiary">
            <Icon name="clock" size={10} />
            <span>{new Date(run.created_at).toLocaleString()}</span>
            {run.trigger && (
              <>
                <span>&middot;</span>
                <span className="capitalize">{run.trigger}</span>
              </>
            )}
          </div>
          {run.error_message && (
            <p className="text-[10px] text-error break-all">{run.error_message}</p>
          )}
          {counts && (
            <p className="text-[10px] text-text-secondary">{counts}</p>
          )}
        </div>
      )}
    </li>
  );
}

export function SyncHistoryPanel({ projectId }: SyncHistoryPanelProps) {
  const [runs, setRuns] = useState<SyncHistoryRun[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const fetchHistory = useCallback(async () => {
    try {
      setError(false);
      const res = await api.projects.syncHistory(projectId);
      if (mountedRef.current) setRuns(res.runs);
    } catch {
      if (mountedRef.current) setError(true);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    setLoading(true);
    fetchHistory();
  }, [fetchHistory]);

  const latest = runs?.[0] ?? null;
  const visibleRuns = showAll ? (runs ?? []) : (runs ?? []).slice(0, 5);

  return (
    <section className="rounded-lg border border-border-subtle bg-surface-1/50 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-text-secondary uppercase tracking-wider">
          Nightly Sync History
        </h3>
        <Tooltip label="Refresh">
          <button
            onClick={() => {
              setLoading(true);
              fetchHistory();
            }}
            aria-label="Refresh sync history"
            className="text-text-tertiary hover:text-text-primary transition-colors"
          >
            <Icon name="refresh-cw" size={13} />
          </button>
        </Tooltip>
      </div>

      {loading ? (
        <p className="text-xs text-text-tertiary">Loading sync history…</p>
      ) : error ? (
        <div className="flex items-center gap-2 text-xs text-error">
          <Icon name="alert-triangle" size={12} />
          <span>Could not load sync history</span>
        </div>
      ) : !runs || runs.length === 0 ? (
        <p className="text-xs text-text-tertiary">No scheduled syncs yet.</p>
      ) : (
        <div className="space-y-2">
          {latest && (
            <div className="flex items-center gap-2 text-xs">
              <Icon
                name={STATUS_ICON[latest.status]}
                size={12}
                className={`shrink-0 ${STATUS_COLOR[latest.status]}`}
              />
              <span className="text-text-secondary">
                Nightly sync:{" "}
                <span className={STATUS_COLOR[latest.status]}>{latest.status}</span>
                {" · "}
                {timeAgo(latest.created_at)}
                {connectionCounts(latest) ? ` · ${connectionCounts(latest)}` : ""}
              </span>
            </div>
          )}

          <ul className="space-y-1">
            {visibleRuns.map((run, idx) => (
              <RunRow key={run.id} run={run} isLatest={idx === 0} />
            ))}
          </ul>

          {(runs?.length ?? 0) > 5 && (
            <button
              onClick={() => setShowAll((v) => !v)}
              className="text-[10px] text-text-tertiary hover:text-text-primary transition-colors"
            >
              {showAll ? "Show less" : `Show all ${runs?.length} runs`}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
