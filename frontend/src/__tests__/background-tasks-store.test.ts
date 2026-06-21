import { describe, it, expect, beforeEach } from "vitest";
import { useBackgroundTasks } from "@/stores/background-tasks-store";
import type { WorkflowEvent } from "@/lib/sse";

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
});
