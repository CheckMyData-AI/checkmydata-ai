"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useBackgroundTasks, type BgTask } from "@/stores/background-tasks-store";
import { useAppStore } from "@/stores/app-store";
import { api } from "@/lib/api";
import { Icon } from "@/components/ui/Icon";
import type { IconName } from "@/components/ui/Icon";
import { Tooltip } from "@/components/ui/Tooltip";
import { STEP_LABELS } from "@/components/tasks/stepLabels";

const PIPELINE_META: Record<string, { label: string; icon: IconName }> = {
  index_repo: { label: "Repository Indexing", icon: "folder-git" },
  db_index: { label: "Database Indexing", icon: "database" },
  code_db_sync: { label: "Code-DB Sync", icon: "refresh-cw" },
};

function useElapsed(startedAt: number, completedAt: number | undefined, active: boolean) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [active]);
  const endTime = active ? Date.now() / 1000 : (completedAt || Date.now() / 1000);
  const seconds = Math.max(0, Math.floor(endTime - startedAt));
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

function TaskItem({ task }: { task: BgTask }) {
  const projects = useAppStore((s) => s.projects);
  const connections = useAppStore((s) => s.connections);
  const dismissTask = useBackgroundTasks((s) => s.dismissTask);
  const elapsed = useElapsed(task.startedAt, task.completedAt, task.status === "running");
  const meta = PIPELINE_META[task.pipeline] || { label: task.pipeline, icon: "activity" as IconName };

  let targetName = "";
  if (task.extra.project_id) {
    const p = projects.find((p) => p.id === task.extra.project_id);
    targetName = p?.name || "";
  }
  if (task.extra.connection_id) {
    const c = connections.find((c) => c.id === task.extra.connection_id);
    targetName = c?.name || targetName;
  }

  const stepLabel = STEP_LABELS[task.currentStep] || task.currentStep;
  const isFinished = task.status !== "running";

  return (
    <div className="px-3 py-2.5 animate-[taskItemIn_0.2s_ease-out] border-b border-border-subtle last:border-b-0">
      <div className="flex items-start gap-2.5">
        <div className="mt-0.5 shrink-0">
          {task.status === "running" && (
            <span className="w-4 h-4 rounded-full border-2 border-accent border-t-transparent animate-spin inline-block" />
          )}
          {task.status === "completed" && (
            <Icon name="check" size={16} className="text-success" />
          )}
          {task.status === "failed" && (
            <Icon name="x" size={16} className="text-error" />
          )}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <Icon name={meta.icon} size={12} className="text-text-tertiary shrink-0" />
            <span className="text-xs font-medium text-text-primary truncate">
              {meta.label}
            </span>
          </div>

          <div className="flex items-center gap-1.5 mt-0.5">
            {targetName && (
              <span className="text-[10px] text-text-tertiary truncate max-w-[140px]">
                {targetName}
              </span>
            )}
            {targetName && (task.status === "running" && stepLabel) && (
              <span className="text-text-muted">·</span>
            )}
            {task.status === "running" && stepLabel && (
              <span className="text-[10px] text-text-secondary truncate">
                {stepLabel}
              </span>
            )}
            {task.status === "running" && task.totalSteps > 0 && (
              <span className="text-[10px] text-text-tertiary tabular-nums">
                {task.stepIndex}/{task.totalSteps}
              </span>
            )}
            {task.status === "completed" && (
              <span className="text-[10px] text-success/70">Completed</span>
            )}
            {task.status === "failed" && (
              <span className="text-[10px] text-error/70 truncate max-w-[180px]" title={task.error}>
                {task.error || "Failed"}
              </span>
            )}
          </div>

          {task.status === "running" && (
            <div className="mt-1.5 h-1 rounded-full bg-surface-2 overflow-hidden">
              <div
                className="h-full bg-accent transition-[width] duration-300"
                style={{ width: `${Math.max(2, task.progressPct)}%` }}
              />
            </div>
          )}
        </div>

        <div className="flex items-center gap-1.5 shrink-0 mt-0.5">
          <span className="text-[10px] text-text-muted tabular-nums">
            {elapsed}
          </span>
          {task.status === "running" && (
            <Tooltip label="Cancel">
              <button
                onClick={() => void api.runs.cancel(task.runId).catch(() => {})}
                className="text-text-muted hover:text-error p-0.5 rounded"
                aria-label="Cancel run"
              >
                <Icon name="x" size={11} />
              </button>
            </Tooltip>
          )}
          {task.status === "failed" && (
            <Tooltip label="Retry">
              <button
                onClick={() => void api.runs.retry(task.runId).catch(() => {})}
                className="text-text-muted hover:text-accent p-0.5 rounded"
                aria-label="Retry run"
              >
                <Icon name="refresh-cw" size={11} />
              </button>
            </Tooltip>
          )}
          {isFinished && (
            <button
              onClick={() => dismissTask(task.runId)}
              className="text-text-muted hover:text-text-secondary p-0.5 rounded"
              aria-label="Dismiss"
            >
              <Icon name="x" size={10} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export function ActiveTasksWidget() {
  const tasks = useBackgroundTasks((s) => s.tasks);
  const activeProject = useAppStore((s) => s.activeProject);
  const [expanded, setExpanded] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const taskList = Object.values(tasks).filter((t) => {
    if (!activeProject) return true;
    const pid = t.extra.project_id;
    return !pid || pid === activeProject.id;
  });
  const runningCount = taskList.filter((t) => t.status === "running").length;
  const failedCount = taskList.filter((t) => t.status === "failed").length;
  const hasAny = taskList.length > 0;
  const prevRunningRef = useRef(runningCount);
  const collapseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const close = useCallback(() => setExpanded(false), []);

  useEffect(() => {
    if (!hasAny && expanded) setExpanded(false);
  }, [hasAny, expanded]);

  useEffect(() => {
    if (runningCount > prevRunningRef.current && runningCount > 0) {
      setExpanded(true);
      if (collapseTimerRef.current) clearTimeout(collapseTimerRef.current);
      collapseTimerRef.current = setTimeout(() => {
        setExpanded(false);
        collapseTimerRef.current = null;
      }, 5000);
    }
    prevRunningRef.current = runningCount;
    return () => {
      if (collapseTimerRef.current) clearTimeout(collapseTimerRef.current);
    };
  }, [runningCount]);

  useEffect(() => {
    if (!expanded) return;
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        close();
      }
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [expanded, close]);

  if (!hasAny) return null;

  const hasFailed = failedCount > 0;
  const pillBg = hasFailed ? "bg-error-muted border-error/30" : "bg-surface-2 border-border-subtle";
  const pillText = hasFailed ? "text-error" : "text-text-secondary";

  let pillLabel: string;
  if (runningCount > 0 && failedCount > 0) {
    pillLabel = `${runningCount} running, ${failedCount} failed`;
  } else if (runningCount > 0) {
    pillLabel = runningCount === 1 ? "1 task" : `${runningCount} tasks`;
  } else if (failedCount > 0) {
    pillLabel = failedCount === 1 ? "1 failed" : `${failedCount} failed`;
  } else {
    pillLabel = taskList.length === 1 ? "1 done" : `${taskList.length} done`;
  }

  const sorted = [...taskList].sort((a, b) => {
    const statusOrder: Record<string, number> = { running: 0, queued: 0, failed: 1, completed: 2 };
    const diff = (statusOrder[a.status] ?? 3) - (statusOrder[b.status] ?? 3);
    if (diff !== 0) return diff;
    return b.startedAt - a.startedAt;
  });

  return (
    <div ref={containerRef} className="relative">
      <span className="sr-only" role="status" aria-live="polite">
        {pillLabel}
      </span>
      <button
        onClick={() => setExpanded((v) => !v)}
        className={`flex items-center gap-2 px-2.5 py-1 rounded-full border text-xs transition-colors
          ${pillBg} ${pillText} hover:brightness-110 animate-[slideDown_0.2s_ease-out]`}
        aria-expanded={expanded}
        aria-haspopup="true"
        aria-label={`Background tasks: ${pillLabel}`}
      >
        {runningCount > 0 ? (
          <span className="w-3 h-3 rounded-full border-[1.5px] border-current border-t-transparent animate-spin inline-block" />
        ) : hasFailed ? (
          <Icon name="x" size={12} />
        ) : (
          <Icon name="check" size={12} />
        )}
        <span aria-hidden="true">{pillLabel}</span>
        <Icon
          name="chevron-down"
          size={10}
          className={`transition-transform ${expanded ? "rotate-180" : ""}`}
        />
      </button>

      {expanded && (
        <div
          className="absolute right-0 top-full mt-1.5 w-80 bg-surface-1 border border-border-subtle rounded-lg shadow-xl z-50 overflow-hidden animate-[slideDown_0.15s_ease-out]"
          role="region"
          aria-label="Background tasks"
        >
          <div className="flex items-center justify-between px-3 py-2 border-b border-border-subtle">
            <span className="text-xs font-medium text-text-secondary">Background Tasks</span>
            <button
              onClick={close}
              className="text-text-muted hover:text-text-secondary p-0.5 rounded"
              aria-label="Close"
            >
              <Icon name="x" size={12} />
            </button>
          </div>

          <div className="max-h-72 overflow-y-auto sidebar-scroll">
            {sorted.map((task) => (
              <TaskItem key={task.runId} task={task} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
