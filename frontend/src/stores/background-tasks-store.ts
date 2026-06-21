import { create } from "zustand";
import type { PipelineStatusResponse } from "@/lib/api/types";
import type { WorkflowEvent } from "@/lib/sse";

const BACKGROUND_PIPELINES = new Set(["index_repo", "db_index", "code_db_sync", "daily_sync"]);
const COMPLETED_DISMISS_MS = 5_000;
const FAILED_DISMISS_MS = 30_000;

export type BgStatus = "running" | "completed" | "failed";

export interface BgTask {
  workflowId: string;
  pipeline: string;
  status: BgStatus;
  currentStep: string;
  currentStepDetail: string;
  startedAt: number;
  completedAt?: number;
  error?: string;
  extra: Record<string, unknown>;
  /** Provenance: set to "sse" when updated via applySseEvent, "poll" when gap-filled by reconcile. */
  source: "sse" | "poll";
}

export type BgPipeline = "index_repo" | "db_index" | "code_db_sync" | "daily_sync";

export interface ApiActiveTask {
  workflow_id: string;
  pipeline: string;
  started_at: number;
  extra: Record<string, unknown>;
}

interface BackgroundTasksState {
  tasks: Record<string, BgTask>;
  pinnedRunningIds: Set<string>;
  applySseEvent: (event: WorkflowEvent) => void;
  reconcileFromActive: (apiTasks: ApiActiveTask[]) => void;
  reconcileFromPipelineStatus: (status: PipelineStatusResponse) => void;
  dismissTask: (workflowId: string) => void;
}

const _dismissTimers = new Map<string, ReturnType<typeof setTimeout>>();

function cancelDismiss(workflowId: string) {
  const existing = _dismissTimers.get(workflowId);
  if (existing) {
    clearTimeout(existing);
    _dismissTimers.delete(workflowId);
  }
}

function scheduleDismiss(workflowId: string, ms: number) {
  if (useBackgroundTasks.getState().pinnedRunningIds.has(workflowId)) {
    return;
  }
  cancelDismiss(workflowId);
  const timer = setTimeout(() => {
    _dismissTimers.delete(workflowId);
    useBackgroundTasks.getState().dismissTask(workflowId);
  }, ms);
  _dismissTimers.set(workflowId, timer);
}

/**
 * Upsert a task in the running state.
 *
 * Precedence rules:
 * - If the task is already terminal (completed/failed), do NOT touch it.
 * - If the task is already running, merge extra only (keep existing source).
 * - Otherwise create a new running task with the given source.
 */
function upsertRunningTask(
  tasks: Record<string, BgTask>,
  workflowId: string,
  pipeline: string,
  extra: Record<string, unknown>,
  startedAt: number,
  source: "sse" | "poll",
): Record<string, BgTask> {
  const existing = tasks[workflowId];
  if (existing) {
    // Terminal guard: never downgrade a completed/failed task.
    if (existing.status === "completed" || existing.status === "failed") {
      return tasks;
    }
    // Task is running — merge extra, keep the existing source provenance.
    if (existing.status === "running") {
      return {
        ...tasks,
        [workflowId]: {
          ...existing,
          extra: { ...existing.extra, ...extra },
        },
      };
    }
    return tasks;
  }
  return {
    ...tasks,
    [workflowId]: {
      workflowId,
      pipeline,
      status: "running",
      currentStep: "",
      currentStepDetail: "",
      startedAt,
      extra,
      source,
    },
  };
}

export const useBackgroundTasks = create<BackgroundTasksState>((set, get) => ({
  tasks: {},
  pinnedRunningIds: new Set<string>(),

  applySseEvent: (event: WorkflowEvent) => {
    const pipeline = event.pipeline || "";
    const wfId = event.workflow_id;
    const isBackground = BACKGROUND_PIPELINES.has(pipeline);
    const existing = get().tasks[wfId];

    if (event.step === "pipeline_start") {
      if (!isBackground) return;
      set((state) => ({
        tasks: upsertRunningTask(
          state.tasks,
          wfId,
          pipeline,
          event.extra || {},
          event.timestamp,
          "sse",
        ),
      }));
      return;
    }

    if (event.step === "pipeline_end") {
      if (!existing) return;
      const finalStatus: BgStatus = event.status === "failed" ? "failed" : "completed";
      set((state) => {
        const nextPinned = new Set(state.pinnedRunningIds);
        nextPinned.delete(wfId);
        return {
          pinnedRunningIds: nextPinned,
          tasks: {
            ...state.tasks,
            [wfId]: {
              ...state.tasks[wfId],
              status: finalStatus,
              completedAt: event.timestamp,
              currentStep: "pipeline_end",
              currentStepDetail: event.detail,
              error: finalStatus === "failed" ? event.detail : undefined,
              source: "sse",
            },
          },
        };
      });
      scheduleDismiss(wfId, finalStatus === "failed" ? FAILED_DISMISS_MS : COMPLETED_DISMISS_MS);
      return;
    }

    // Intermediate step event.
    if (existing) {
      if (existing.status !== "running") return;
      set((state) => ({
        tasks: {
          ...state.tasks,
          [wfId]: {
            ...state.tasks[wfId],
            currentStep: event.step,
            currentStepDetail: event.detail,
            source: "sse",
          },
        },
      }));
      return;
    }

    // Unknown workflow mid-stream — create it if it's a background pipeline.
    if (!isBackground) return;
    set((state) => {
      const updated = upsertRunningTask(
        state.tasks,
        wfId,
        pipeline,
        event.extra || {},
        event.timestamp,
        "sse",
      );
      return {
        tasks: {
          ...updated,
          [wfId]: {
            ...updated[wfId],
            currentStep: event.step,
            currentStepDetail: event.detail,
            source: "sse",
          },
        },
      };
    });
  },

  reconcileFromActive: (apiTasks: ApiActiveTask[]) => {
    set((state) => {
      let updated = { ...state.tasks };
      for (const t of apiTasks) {
        const existing = updated[t.workflow_id];
        // Never overwrite a terminal task or an SSE-sourced running task.
        if (existing) {
          if (
            existing.status === "completed" ||
            existing.status === "failed" ||
            (existing.status === "running" && existing.source === "sse")
          ) {
            continue;
          }
        }
        updated = upsertRunningTask(
          updated,
          t.workflow_id,
          t.pipeline,
          t.extra || {},
          t.started_at,
          "poll",
        );
      }
      return { tasks: updated };
    });
  },

  reconcileFromPipelineStatus: (status: PipelineStatusResponse) => {
    const now = Date.now() / 1000;
    const pinned = new Set<string>();

    set((state) => {
      let updated = { ...state.tasks };

      if (status.repo.is_indexing) {
        const wfId = status.repo.workflow_id || `repo:${status.project_id}`;
        pinned.add(wfId);
        cancelDismiss(wfId);
        const existing = updated[wfId];
        // Only gap-fill; do not overwrite terminal or SSE-running tasks.
        if (
          !existing ||
          (existing.status === "running" && existing.source !== "sse")
        ) {
          updated = upsertRunningTask(
            updated,
            wfId,
            "index_repo",
            { project_id: status.project_id },
            now,
            "poll",
          );
        }
      }

      for (const conn of status.connections) {
        if (conn.db_index.is_indexing) {
          const wfId = `db:${conn.connection_id}`;
          pinned.add(wfId);
          cancelDismiss(wfId);
          const existing = updated[wfId];
          if (
            !existing ||
            (existing.status === "running" && existing.source !== "sse")
          ) {
            updated = upsertRunningTask(
              updated,
              wfId,
              "db_index",
              { project_id: status.project_id, connection_id: conn.connection_id },
              now,
              "poll",
            );
          }
        }
        if (conn.code_db_sync.is_syncing) {
          const wfId = `sync:${conn.connection_id}`;
          pinned.add(wfId);
          cancelDismiss(wfId);
          const existing = updated[wfId];
          if (
            !existing ||
            (existing.status === "running" && existing.source !== "sse")
          ) {
            updated = upsertRunningTask(
              updated,
              wfId,
              "code_db_sync",
              { project_id: status.project_id, connection_id: conn.connection_id },
              now,
              "poll",
            );
          }
        }
      }

      return { tasks: updated, pinnedRunningIds: pinned };
    });
  },

  dismissTask: (workflowId: string) => {
    cancelDismiss(workflowId);
    set((state) => {
      const nextPinned = new Set(state.pinnedRunningIds);
      nextPinned.delete(workflowId);
      const { [workflowId]: _, ...rest } = state.tasks;
      return { tasks: rest, pinnedRunningIds: nextPinned };
    });
  },
}));
