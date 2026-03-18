import { create } from "zustand";
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
  processEvent: (event: WorkflowEvent) => void;
  seedFromApi: (apiTasks: ApiActiveTask[]) => void;
  dismissTask: (workflowId: string) => void;
}

const _dismissTimers = new Map<string, ReturnType<typeof setTimeout>>();

function scheduleDismiss(workflowId: string, ms: number) {
  const existing = _dismissTimers.get(workflowId);
  if (existing) clearTimeout(existing);
  const timer = setTimeout(() => {
    _dismissTimers.delete(workflowId);
    useTaskStore.getState().dismissTask(workflowId);
  }, ms);
  _dismissTimers.set(workflowId, timer);
}

export const useTaskStore = create<TaskState>((set, get) => ({
  tasks: {},

  processEvent: (event: WorkflowEvent) => {
    const pipeline = event.pipeline || "";
    const wfId = event.workflow_id;
    const isBackground = BACKGROUND_PIPELINES.has(pipeline);
    const existing = get().tasks[wfId];

    if (event.step === "pipeline_start") {
      if (!isBackground) return;
      set((state) => ({
        tasks: {
          ...state.tasks,
          [wfId]: {
            workflowId: wfId,
            pipeline,
            status: "running",
            currentStep: "pipeline_start",
            currentStepDetail: event.detail,
            startedAt: event.timestamp,
            extra: event.extra || {},
          },
        },
      }));
      return;
    }

    if (event.step === "pipeline_end") {
      if (!existing) return;
      const finalStatus: ActiveTask["status"] = event.status === "failed" ? "failed" : "completed";
      set((state) => ({
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
      }));
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
    set((state) => ({
      tasks: {
        ...state.tasks,
        [wfId]: {
          workflowId: wfId,
          pipeline,
          status: "running",
          currentStep: event.step,
          currentStepDetail: event.detail,
          startedAt: event.timestamp,
          extra: event.extra || {},
        },
      },
    }));
  },

  seedFromApi: (apiTasks: ApiActiveTask[]) => {
    set((state) => {
      const updated = { ...state.tasks };
      for (const t of apiTasks) {
        if (updated[t.workflow_id]) continue;
        updated[t.workflow_id] = {
          workflowId: t.workflow_id,
          pipeline: t.pipeline,
          status: "running",
          currentStep: "",
          currentStepDetail: "",
          startedAt: t.started_at,
          extra: t.extra || {},
        };
      }
      return { tasks: updated };
    });
  },

  dismissTask: (workflowId: string) => {
    const timer = _dismissTimers.get(workflowId);
    if (timer) {
      clearTimeout(timer);
      _dismissTimers.delete(workflowId);
    }
    set((state) => {
      const { [workflowId]: _, ...rest } = state.tasks;
      return { tasks: rest };
    });
  },
}));
