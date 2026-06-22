import { describe, it, expect, beforeEach } from "vitest";
import { useBackgroundTasks } from "@/stores/background-tasks-store";

function reset() {
  useBackgroundTasks.setState({ tasks: {}, pinnedRunningIds: new Set() });
}

describe("runs store progress + optimistic", () => {
  beforeEach(reset);

  it("optimistic insert then SSE upgrades with progress", () => {
    const s = useBackgroundTasks.getState();
    s.insertOptimistic({
      runId: "r1",
      workflowId: "w1",
      kind: "db_index",
      projectId: "p",
      connectionId: "c",
    });
    expect(useBackgroundTasks.getState().tasks["r1"].status).toBe("queued");

    s.applySseEvent({
      workflow_id: "w1",
      step: "introspect_schema",
      status: "started",
      detail: "",
      elapsed_ms: null,
      timestamp: 1,
      pipeline: "db_index",
      extra: {},
      run_id: "r1",
      kind: "db_index",
      step_index: 1,
      total_steps: 6,
      progress_pct: 16,
    });
    const t = useBackgroundTasks.getState().tasks["r1"];
    expect(t.status).toBe("running");
    expect(t.progressPct).toBe(16);
    expect(t.totalSteps).toBe(6);
    expect(t.source).toBe("sse");
  });

  it("pipeline_end marks terminal", () => {
    const s = useBackgroundTasks.getState();
    s.insertOptimistic({
      runId: "r2",
      workflowId: "w2",
      kind: "db_index",
      projectId: "p",
      connectionId: "c",
    });
    s.applySseEvent({
      workflow_id: "w2",
      step: "pipeline_end",
      status: "completed",
      detail: "",
      elapsed_ms: null,
      timestamp: 2,
      pipeline: "db_index",
      extra: {},
      run_id: "r2",
    });
    const t = useBackgroundTasks.getState().tasks["r2"];
    expect(t.status).toBe("completed");
    expect(t.progressPct).toBe(100);
  });
});
