import { create } from "zustand";
import type { PipelineStatusResponse } from "@/lib/api/types";
import type { WorkflowEvent } from "@/lib/sse";

const BACKGROUND_PIPELINES = new Set(["index_repo", "db_index", "code_db_sync"]);
const COMPLETED_DISMISS_MS = 5_000;
const FAILED_DISMISS_MS = 30_000;

export interface ActiveTask {
  workflowId: string;
  pipeline: string;
  status: "running" | "completed" | "failed";
  currentStep: string;
  currentStepDetail: string;
  startedAt: number;
  completedAt?: number;
  error?: string;
  extra: Record<string, unknown>;
}

export interface ApiActiveTask {
  workflow_id: string;
  pipeline: string;
  started_at: number;
  extra: Record<string, unknown>;
}

interface TaskState {
  tasks: Record<string, ActiveTask>;
  pinnedRunningIds: Set<string>;
  processEvent: (event: WorkflowEvent) => void;
  seedFromApi: (apiTasks: ApiActiveTask[]) => void;
  seedFromPipelineStatus: (status: PipelineStatusResponse) => void;
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
  if (useTaskStore.getState().pinnedRunningIds.has(workflowId)) {
    return;
  }
  cancelDismiss(workflowId);
  const timer = setTimeout(() => {
    _dismissTimers.delete(workflowId);
    useTaskStore.getState().dismissTask(workflowId);
  }, ms);
  _dismissTimers.set(workflowId, timer);
}

function upsertRunningTask(
  tasks: Record<string, ActiveTask>,
  workflowId: string,
  pipeline: string,
  extra: Record<string, unknown>,
  startedAt: number,
): Record<string, ActiveTask> {
  const existing = tasks[workflowId];
  if (existing) {
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
    },
  };
}

export const useTaskStore = create<TaskState>((set, get) => ({
  tasks: {},
  pinnedRunningIds: new Set<string>(),

  processEvent: (event: WorkflowEvent) => {
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
        ),
      }));
      return;
    }

    if (event.step === "pipeline_end") {
      if (!existing) return;
      const finalStatus: ActiveTask["status"] = event.status === "failed" ? "failed" : "completed";
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
            },
          },
        };
      });
      scheduleDismiss(wfId, finalStatus === "failed" ? FAILED_DISMISS_MS : COMPLETED_DISMISS_MS);
      return;
    }

    if (existing) {
      if (existing.status !== "running") return;
      set((state) => ({
        tasks: {
          ...state.tasks,
          [wfId]: {
            ...state.tasks[wfId],
            currentStep: event.step,
            currentStepDetail: event.detail,
          },
        },
      }));
      return;
    }

    if (!isBackground) return;
    set((state) => {
      const updated = upsertRunningTask(
        state.tasks,
        wfId,
        pipeline,
        event.extra || {},
        event.timestamp,
      );
      return {
        tasks: {
          ...updated,
          [wfId]: {
            ...updated[wfId],
            currentStep: event.step,
            currentStepDetail: event.detail,
          },
        },
      };
    });
  },

  seedFromApi: (apiTasks: ApiActiveTask[]) => {
    set((state) => {
      let updated = { ...state.tasks };
      for (const t of apiTasks) {
        if (updated[t.workflow_id]?.status === "running") continue;
        updated = upsertRunningTask(
          updated,
          t.workflow_id,
          t.pipeline,
          t.extra || {},
          t.started_at,
        );
      }
      return { tasks: updated };
    });
  },

  seedFromPipelineStatus: (status: PipelineStatusResponse) => {
    const now = Date.now() / 1000;
    const pinned = new Set<string>();

    set((state) => {
      let updated = { ...state.tasks };

      if (status.repo.is_indexing) {
        const wfId = status.repo.workflow_id || `repo:${status.project_id}`;
        pinned.add(wfId);
        cancelDismiss(wfId);
        updated = upsertRunningTask(updated, wfId, "index_repo", { project_id: status.project_id }, now);
      }

      for (const conn of status.connections) {
        if (conn.db_index.is_indexing) {
          const wfId = `db:${conn.connection_id}`;
          pinned.add(wfId);
          cancelDismiss(wfId);
          updated = upsertRunningTask(
            updated,
            wfId,
            "db_index",
            { project_id: status.project_id, connection_id: conn.connection_id },
            now,
          );
        }
        if (conn.code_db_sync.is_syncing) {
          const wfId = `sync:${conn.connection_id}`;
          pinned.add(wfId);
          cancelDismiss(wfId);
          updated = upsertRunningTask(
            updated,
            wfId,
            "code_db_sync",
            { project_id: status.project_id, connection_id: conn.connection_id },
            now,
          );
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
