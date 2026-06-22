import { describe, it, expect, beforeEach } from "vitest";
import { useBackgroundTasks } from "@/stores/background-tasks-store";
import type { WorkflowEvent } from "@/lib/sse";
import type { PipelineStatusResponse } from "@/lib/api/types";

function ev(p: Partial<WorkflowEvent>): WorkflowEvent {
  return {
    workflow_id: "w",
    pipeline: "db_index",
    step: "pipeline_start",
    status: "started",
    detail: "",
    timestamp: Date.now() / 1000,
    extra: {},
    elapsed_ms: null,
    ...p,
  } as WorkflowEvent;
}

describe("background-tasks-store", () => {
  beforeEach(() => useBackgroundTasks.setState({ tasks: {}, pinnedRunningIds: new Set() }));

  it("creates a running task from an SSE pipeline_start", () => {
    useBackgroundTasks.getState().applySseEvent(ev({ workflow_id: "a" }));
    expect(useBackgroundTasks.getState().tasks["a"].status).toBe("running");
    expect(useBackgroundTasks.getState().tasks["a"].source).toBe("sse");
  });

  it("terminal SSE wins and is not downgraded by a later poll", () => {
    const s = useBackgroundTasks.getState();
    s.applySseEvent(ev({ workflow_id: "b" }));
    s.applySseEvent(ev({ workflow_id: "b", step: "pipeline_end", status: "completed" }));
    expect(useBackgroundTasks.getState().tasks["b"].status).toBe("completed");
    s.reconcileFromActive([{ workflow_id: "b", pipeline: "db_index", started_at: 1, extra: {} }]);
    expect(useBackgroundTasks.getState().tasks["b"].status).toBe("completed"); // not flipped to running
  });

  it("poll gap-fills a running task not seen via SSE", () => {
    useBackgroundTasks.getState().reconcileFromActive([
      { workflow_id: "c", pipeline: "daily_sync", started_at: 1, extra: {} },
    ]);
    expect(useBackgroundTasks.getState().tasks["c"].status).toBe("running");
    expect(useBackgroundTasks.getState().tasks["c"].source).toBe("poll");
  });

  it("reconcileFromPipelineStatus does not overwrite an SSE-running task", () => {
    const s = useBackgroundTasks.getState();
    // Establish an SSE-sourced running task for the db_index workflow on connection "conn1".
    const wfId = "db:conn1";
    s.applySseEvent(
      ev({ workflow_id: wfId, pipeline: "db_index", step: "pipeline_start" }),
    );
    expect(useBackgroundTasks.getState().tasks[wfId].source).toBe("sse");

    // Now poll arrives saying the same connection is indexing.
    const pipelineStatus: PipelineStatusResponse = {
      project_id: "proj1",
      repo: {
        is_indexing: false,
        workflow_id: null,
        last_indexed_at: null,
        last_indexed_commit: null,
      },
      connections: [
        {
          connection_id: "conn1",
          connection_name: "Test DB",
          db_index: {
            is_indexing: true,
            indexing_status: "running",
            indexed_at: null,
            table_count: 0,
          },
          code_db_sync: {
            is_syncing: false,
            sync_status: "idle",
            synced_at: null,
            total_tables: 0,
            synced_tables: 0,
          },
        },
      ],
      any_running: true,
    };
    s.reconcileFromPipelineStatus(pipelineStatus);

    // SSE provenance must be preserved — poll must not overwrite it.
    const task = useBackgroundTasks.getState().tasks[wfId];
    expect(task.status).toBe("running");
    expect(task.source).toBe("sse");
  });
});
