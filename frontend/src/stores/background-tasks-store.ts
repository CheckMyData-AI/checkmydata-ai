import { create } from "zustand";
import type { PipelineStatusResponse } from "@/lib/api/types";
import type { WorkflowEvent } from "@/lib/sse";

const BACKGROUND_PIPELINES = new Set(["index_repo", "db_index", "code_db_sync", "daily_sync"]);
const COMPLETED_DISMISS_MS = 5_000;
const FAILED_DISMISS_MS = 30_000;

export type BgStatus = "queued" | "running" | "completed" | "failed";
export type BgSource = "sse" | "poll" | "optimistic";

export interface BgTask {
  /** Stable key: the run id when known, else the workflow id. */
  runId: string;
  workflowId: string;
  pipeline: string;
  kind: string;
  status: BgStatus;
  currentStep: string;
  currentStepDetail: string;
  stepIndex: number;
  totalSteps: number;
  progressPct: number;
  connectionId: string | null;
  startedAt: number;
  completedAt?: number;
  error?: string;
  extra: Record<string, unknown>;
  source: BgSource;
}

export type BgPipeline = "index_repo" | "db_index" | "code_db_sync" | "daily_sync";

export interface ApiActiveTask {
  workflow_id: string;
  run_id?: string;
  pipeline: string;
  kind?: string;
  started_at: number;
  progress_pct?: number;
  extra: Record<string, unknown>;
}

export interface OptimisticRun {
  runId: string;
  workflowId: string;
  kind: string;
  projectId: string;
  connectionId: string | null;
}

interface BackgroundTasksState {
  tasks: Record<string, BgTask>;
  pinnedRunningIds: Set<string>;
  applySseEvent: (event: WorkflowEvent) => void;
  insertOptimistic: (run: OptimisticRun) => void;
  reconcileFromActive: (apiTasks: ApiActiveTask[]) => void;
  reconcileFromPipelineStatus: (status: PipelineStatusResponse) => void;
  dismissTask: (key: string) => void;
}

const _dismissTimers = new Map<string, ReturnType<typeof setTimeout>>();

function cancelDismiss(key: string) {
  const existing = _dismissTimers.get(key);
  if (existing) {
    clearTimeout(existing);
    _dismissTimers.delete(key);
  }
}

function scheduleDismiss(key: string, ms: number) {
  if (useBackgroundTasks.getState().pinnedRunningIds.has(key)) return;
  cancelDismiss(key);
  const timer = setTimeout(() => {
    _dismissTimers.delete(key);
    useBackgroundTasks.getState().dismissTask(key);
  }, ms);
  _dismissTimers.set(key, timer);
}

const TERMINAL = (s: BgStatus) => s === "completed" || s === "failed";

/** A poll/optimistic source may refresh only non-terminal, non-SSE-running tasks. */
function pollMayTouch(existing: BgTask | undefined): boolean {
  if (!existing) return true;
  if (TERMINAL(existing.status)) return false;
  if (existing.source === "sse") return false;
  return true;
}

function keyOf(runId: string | undefined | null, workflowId: string): string {
  return runId || workflowId;
}

export const useBackgroundTasks = create<BackgroundTasksState>((set, get) => ({
  tasks: {},
  pinnedRunningIds: new Set<string>(),

  applySseEvent: (event: WorkflowEvent) => {
    const pipeline = event.pipeline || "";
    const kind = event.kind || pipeline;
    const key = keyOf(event.run_id, event.workflow_id);
    const isBackground = BACKGROUND_PIPELINES.has(pipeline);
    const existing = get().tasks[key];

    const progress = {
      ...(event.step_index !== undefined ? { stepIndex: event.step_index } : {}),
      ...(event.total_steps !== undefined ? { totalSteps: event.total_steps } : {}),
      ...(event.progress_pct !== undefined ? { progressPct: event.progress_pct } : {}),
    };

    if (event.step === "pipeline_end") {
      if (!existing) return;
      const finalStatus: BgStatus = event.status === "failed" ? "failed" : "completed";
      set((state) => {
        const nextPinned = new Set(state.pinnedRunningIds);
        nextPinned.delete(key);
        return {
          pinnedRunningIds: nextPinned,
          tasks: {
            ...state.tasks,
            [key]: {
              ...state.tasks[key],
              status: finalStatus,
              completedAt: event.timestamp,
              currentStep: "pipeline_end",
              currentStepDetail: event.detail,
              progressPct: finalStatus === "completed" ? 100 : state.tasks[key].progressPct,
              error: finalStatus === "failed" ? event.detail : undefined,
              source: "sse",
            },
          },
        };
      });
      scheduleDismiss(key, finalStatus === "failed" ? FAILED_DISMISS_MS : COMPLETED_DISMISS_MS);
      return;
    }

    if (existing) {
      // Never resurrect a terminal task from a late step event.
      if (TERMINAL(existing.status)) return;
      set((state) => ({
        tasks: {
          ...state.tasks,
          [key]: {
            ...state.tasks[key],
            status: "running",
            currentStep: event.step === "pipeline_start" ? state.tasks[key].currentStep : event.step,
            currentStepDetail: event.detail,
            ...progress,
            source: "sse",
          },
        },
      }));
      return;
    }

    // Unknown run mid-stream — create it if it's a background pipeline.
    if (!isBackground) return;
    set((state) => ({
      tasks: {
        ...state.tasks,
        [key]: {
          runId: event.run_id || key,
          workflowId: event.workflow_id,
          pipeline,
          kind,
          status: "running",
          currentStep: event.step === "pipeline_start" ? "" : event.step,
          currentStepDetail: event.detail,
          stepIndex: event.step_index ?? 0,
          totalSteps: event.total_steps ?? 0,
          progressPct: event.progress_pct ?? 0,
          connectionId: (event.extra?.connection_id as string | undefined) ?? null,
          startedAt: event.timestamp,
          extra: event.extra || {},
          source: "sse",
        },
      },
    }));
  },

  insertOptimistic: (run: OptimisticRun) => {
    set((state) => {
      if (state.tasks[run.runId]) return state; // never downgrade an existing task
      return {
        tasks: {
          ...state.tasks,
          [run.runId]: {
            runId: run.runId,
            workflowId: run.workflowId,
            pipeline: run.kind,
            kind: run.kind,
            status: "queued",
            currentStep: "",
            currentStepDetail: "",
            stepIndex: 0,
            totalSteps: 0,
            progressPct: 0,
            connectionId: run.connectionId,
            startedAt: Date.now() / 1000,
            extra: { project_id: run.projectId, connection_id: run.connectionId },
            source: "optimistic",
          },
        },
      };
    });
  },

  reconcileFromActive: (apiTasks: ApiActiveTask[]) => {
    set((state) => {
      const updated = { ...state.tasks };
      for (const t of apiTasks) {
        const key = keyOf(t.run_id, t.workflow_id);
        const existing = updated[key];
        if (!pollMayTouch(existing)) continue;
        const connId = (t.extra?.connection_id as string | undefined) ?? null;
        updated[key] = {
          runId: t.run_id || key,
          workflowId: t.workflow_id,
          pipeline: t.pipeline,
          kind: t.kind || t.pipeline,
          status: "running",
          currentStep: existing?.currentStep ?? "",
          currentStepDetail: existing?.currentStepDetail ?? "",
          stepIndex: existing?.stepIndex ?? 0,
          totalSteps: existing?.totalSteps ?? 0,
          progressPct: t.progress_pct ?? existing?.progressPct ?? 0,
          connectionId: connId,
          startedAt: existing?.startedAt ?? t.started_at,
          extra: { ...(existing?.extra ?? {}), ...(t.extra || {}) },
          source: existing?.source === "optimistic" ? "poll" : (existing?.source ?? "poll"),
        };
      }
      return { tasks: updated };
    });
  },

  reconcileFromPipelineStatus: (status: PipelineStatusResponse) => {
    const now = Date.now() / 1000;
    const pinned = new Set<string>();

    const apply = (
      updated: Record<string, BgTask>,
      block: {
        run_id?: string | null;
        workflow_id?: string | null;
        progress_pct?: number;
        step_index?: number;
        total_steps?: number;
        current_step?: string | null;
      },
      kind: string,
      connectionId: string | null,
      fallbackKey: string,
    ) => {
      const key = block.run_id || block.workflow_id || fallbackKey;
      pinned.add(key);
      cancelDismiss(key);
      const existing = updated[key];
      if (!pollMayTouch(existing)) return;
      updated[key] = {
        runId: block.run_id || key,
        workflowId: block.workflow_id || existing?.workflowId || key,
        pipeline: kind,
        kind,
        status: "running",
        currentStep: block.current_step ?? existing?.currentStep ?? "",
        currentStepDetail: existing?.currentStepDetail ?? "",
        stepIndex: block.step_index ?? existing?.stepIndex ?? 0,
        totalSteps: block.total_steps ?? existing?.totalSteps ?? 0,
        progressPct: block.progress_pct ?? existing?.progressPct ?? 0,
        connectionId,
        startedAt: existing?.startedAt ?? now,
        extra: { project_id: status.project_id, connection_id: connectionId },
        source: existing?.source === "sse" ? "sse" : "poll",
      };
    };

    set((state) => {
      const updated = { ...state.tasks };
      if (status.repo.is_indexing) {
        apply(updated, status.repo, "index_repo", null, `repo:${status.project_id}`);
      }
      for (const conn of status.connections) {
        if (conn.db_index.is_indexing) {
          apply(updated, conn.db_index, "db_index", conn.connection_id, `db:${conn.connection_id}`);
        }
        if (conn.code_db_sync.is_syncing) {
          apply(
            updated,
            conn.code_db_sync,
            "code_db_sync",
            conn.connection_id,
            `sync:${conn.connection_id}`,
          );
        }
      }
      return { tasks: updated, pinnedRunningIds: pinned };
    });
  },

  dismissTask: (key: string) => {
    cancelDismiss(key);
    set((state) => {
      const nextPinned = new Set(state.pinnedRunningIds);
      nextPinned.delete(key);
      const { [key]: _, ...rest } = state.tasks;
      return { tasks: rest, pinnedRunningIds: nextPinned };
    });
  },
}));
