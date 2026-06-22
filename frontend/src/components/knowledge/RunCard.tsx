"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useBackgroundTasks, type BgTask } from "@/stores/background-tasks-store";
import type { RunHistoryItem } from "@/lib/api/types";
import { Icon } from "@/components/ui/Icon";
import { Tooltip } from "@/components/ui/Tooltip";
import { stepLabel } from "@/components/tasks/stepLabels";

interface RunCardProps {
  title: string;
  kind: "index_repo" | "db_index" | "code_db_sync";
  projectId: string;
  connectionId: string | null;
  /** Trigger a fresh run for this kind (idle-state primary action). */
  onTrigger: () => void;
  triggerLabel: string;
  triggerDisabled?: boolean;
}

const STATUS_RANK: Record<string, number> = {
  running: 0,
  queued: 0,
  failed: 1,
  completed: 2,
};

export function RunCard({
  title,
  kind,
  projectId,
  connectionId,
  onTrigger,
  triggerLabel,
  triggerDisabled,
}: RunCardProps) {
  const tasks = useBackgroundTasks((s) => s.tasks);
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<RunHistoryItem[] | null>(null);

  const task: BgTask | undefined = useMemo(() => {
    const matches = Object.values(tasks).filter(
      (t) => t.kind === kind && (kind === "index_repo" || t.connectionId === connectionId),
    );
    matches.sort(
      (a, b) => (STATUS_RANK[a.status] ?? 3) - (STATUS_RANK[b.status] ?? 3) || b.startedAt - a.startedAt,
    );
    return matches[0];
  }, [tasks, kind, connectionId]);

  const loadHistory = async () => {
    setShowHistory((v) => !v);
    if (history === null) {
      try {
        const rows = await api.logs.runs(projectId, { kind, limit: 10 });
        setHistory(rows);
      } catch {
        setHistory([]);
      }
    }
  };

  const running = task?.status === "running" || task?.status === "queued";
  const failed = task?.status === "failed";

  return (
    <div className="rounded-md border border-border-subtle bg-surface-0/50 p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <Icon
            name={kind === "index_repo" ? "folder-git" : kind === "db_index" ? "database" : "refresh-cw"}
            size={13}
            className="text-text-tertiary shrink-0"
          />
          <span className="text-xs font-medium text-text-primary truncate">{title}</span>
        </div>
        {running ? (
          <Tooltip label="Cancel">
            <button
              aria-label={`Cancel ${title}`}
              onClick={() => task && void api.runs.cancel(task.runId).catch(() => {})}
              className="text-[10px] px-2 py-1 rounded text-text-secondary hover:text-error border border-border-subtle"
            >
              Cancel
            </button>
          </Tooltip>
        ) : failed ? (
          <button
            aria-label={`Retry ${title}`}
            onClick={() => task && void api.runs.retry(task.runId).catch(() => {})}
            className="text-[10px] px-2 py-1 rounded bg-accent text-white hover:bg-accent-hover"
          >
            Retry
          </button>
        ) : (
          <button
            aria-label={triggerLabel}
            onClick={onTrigger}
            disabled={triggerDisabled}
            className="text-[10px] px-2 py-1 rounded bg-accent text-white hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {triggerLabel}
          </button>
        )}
      </div>

      {running && task && (
        <div className="space-y-1">
          <div className="flex items-center justify-between text-[10px] text-text-tertiary">
            <span className="truncate">
              {task.totalSteps > 0 ? `${task.stepIndex} of ${task.totalSteps}` : "Starting"}
              {task.currentStep ? ` · ${stepLabel(task.currentStep)}` : ""}
            </span>
            <span className="tabular-nums">{task.progressPct}%</span>
          </div>
          <div className="h-1 rounded-full bg-surface-2 overflow-hidden">
            <div
              className="h-full bg-accent transition-[width] duration-300"
              style={{ width: `${Math.max(2, task.progressPct)}%` }}
            />
          </div>
        </div>
      )}

      {failed && task && (
        <p className="text-[10px] text-error/80 truncate" title={task.error}>
          {task.error || "Run failed"}
        </p>
      )}

      <button
        onClick={loadHistory}
        className="flex items-center gap-1 text-[10px] text-text-tertiary hover:text-text-secondary"
        aria-expanded={showHistory}
      >
        <Icon name="chevron-down" size={9} className={showHistory ? "rotate-180" : ""} />
        History
      </button>

      {showHistory && (
        <ul className="space-y-1 border-t border-border-subtle pt-1.5">
          {history === null ? (
            <li className="text-[10px] text-text-muted">Loading…</li>
          ) : history.length === 0 ? (
            <li className="text-[10px] text-text-muted">No previous runs</li>
          ) : (
            history.map((r) => (
              <li key={r.id} className="flex items-center justify-between text-[10px]">
                <span
                  className={
                    r.status === "failed"
                      ? "text-error"
                      : r.status === "completed"
                        ? "text-success"
                        : "text-text-secondary"
                  }
                >
                  {r.status}
                </span>
                <span className="text-text-muted tabular-nums">
                  {r.finished_at ? new Date(r.finished_at).toLocaleString() : "—"}
                </span>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
