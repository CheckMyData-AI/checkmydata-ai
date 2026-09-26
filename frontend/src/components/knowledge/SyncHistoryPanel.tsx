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
  if (!Array.isArray(connections) || connections.length === 0) return null;
  // A connection is done when both of its steps completed — the shape the daily sync
  // writes (`{connection_id, db_index: {status}, code_db_sync: {status}}`).
  const stepOk = (c: Record<string, unknown>, key: string) =>
    (c[key] as Record<string, unknown> | undefined)?.["status"] === "completed";
  const succeeded = connections.filter(
    (c) =>
      typeof c === "object" &&
      c !== null &&
      stepOk(c as Record<string, unknown>, "db_index") &&
      stepOk(c as Record<string, unknown>, "code_db_sync"),
  ).length;
  return `${succeeded}/${connections.length} connections`;
}

type Tone = "ok" | "warn" | "bad" | "muted" | "busy";

/** The run's own verdict when it gave one, else its lifecycle status. */
function verdict(run: SyncHistoryRun): { label: string; tone: Tone } {
  const o = run.outcome;
  if (o === "success" || o === "ok") return { label: "success", tone: "ok" };
  if (o === "partial") return { label: "partial", tone: "warn" };
  if (o === "failed") return { label: "failed", tone: "bad" };
  if (o === "skipped") return { label: "skipped", tone: "muted" };
  switch (run.status) {
    case "completed":
      return { label: "completed", tone: "ok" };
    case "failed":
      return { label: "failed", tone: "bad" };
    case "cancelled":
      return { label: "cancelled", tone: "muted" };
    case "queued":
    case "running":
    case "cancelling":
      return { label: run.status, tone: "busy" };
    default:
      return { label: run.status || "unknown", tone: "muted" };
  }
}

const TONE_ICON: Record<Tone, Parameters<typeof Icon>[0]["name"]> = {
  ok: "check",
  warn: "alert-triangle",
  bad: "alert-triangle",
  muted: "minus",
  busy: "loader",
};

const TONE_COLOR: Record<Tone, string> = {
  ok: "text-success",
  warn: "text-warning",
  bad: "text-error",
  muted: "text-text-tertiary",
  busy: "text-text-secondary",
};

const KIND_LABEL: Record<string, string> = {
  daily_sync: "Nightly sync",
  analytics_collect: "Analytics collection",
};

function RunRow({ run, isLatest }: { run: SyncHistoryRun; isLatest: boolean }) {
  const [expanded, setExpanded] = useState(isLatest);
  const counts = connectionCounts(run);
  const when = run.started_at ?? run.created_at;
  const ago = when ? timeAgo(when) : null;
  const { label, tone } = verdict(run);
  const statusColor = TONE_COLOR[tone];
  const iconName = TONE_ICON[tone];
  const kind =
    run.kind === "daily_sync" && run.connection_id
      ? "Nightly sync · one connection"
      : (KIND_LABEL[run.kind] ?? run.kind);

  const summary = [kind, label, ago, counts].filter(Boolean).join(" · ");

  return (
    <li className="rounded-md border border-border-subtle bg-surface-0/50">
      <div className="flex items-center gap-2 px-2.5 py-2">
        <Icon name={iconName} size={12} className={`shrink-0 ${statusColor}`} />
        <span className={`text-xs flex-1 min-w-0 truncate ${statusColor}`}>{summary}</span>
        {run.duration_seconds !== null && (
          <span className="text-kicker text-text-tertiary shrink-0">
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
          <div className="flex items-center gap-1.5 text-kicker text-text-tertiary">
            <Icon name="clock" size={10} />
            <span>{when ? new Date(when).toLocaleString() : "not started"}</span>
            {run.trigger && (
              <>
                <span>&middot;</span>
                <span className="capitalize">{run.trigger}</span>
              </>
            )}
          </div>
          {run.error && (
            <p className="text-kicker text-error break-all">{run.error}</p>
          )}
          {counts && (
            <p className="text-kicker text-text-secondary">{counts}</p>
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

  // The header speaks for the nightly sync; collections are listed below it (B-28).
  // The repository row (no connection_id). On a multi-connection project each
  // connection writes its own `daily_sync` row after it (T07d), and those are listed
  // below rather than summarised here.
  const latest = runs?.find((r) => r.kind === "daily_sync" && !r.connection_id) ?? null;
  const latestVerdict = latest ? verdict(latest) : null;
  const latestWhen = latest ? latest.started_at ?? latest.created_at : null;
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
                name={TONE_ICON[latestVerdict!.tone]}
                size={12}
                className={`shrink-0 ${TONE_COLOR[latestVerdict!.tone]}`}
              />
              <span className="text-text-secondary">
                Nightly sync:{" "}
                <span className={TONE_COLOR[latestVerdict!.tone]}>{latestVerdict!.label}</span>
                {latestWhen ? ` · ${timeAgo(latestWhen)}` : ""}
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
              className="text-kicker text-text-tertiary hover:text-text-primary transition-colors"
            >
              {showAll ? "Show less" : `Show all ${runs?.length} runs`}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
