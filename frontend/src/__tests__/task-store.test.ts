import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { useTaskStore } from "@/stores/task-store";
import type { WorkflowEvent } from "@/lib/sse";

function makeEvent(overrides: Partial<WorkflowEvent> = {}): WorkflowEvent {
  return {
    workflow_id: "wf-test-1",
    step: "pipeline_start",
    status: "started",
    detail: "Starting index_repo",
    elapsed_ms: null,
    timestamp: Date.now() / 1000,
    pipeline: "index_repo",
    extra: { project_id: "p1" },
    ...overrides,
  };
}

beforeEach(() => {
  useTaskStore.setState({ tasks: {} });
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("task-store", () => {
  it("processEvent creates task on pipeline_start", () => {
    useTaskStore.getState().processEvent(makeEvent());
    const tasks = useTaskStore.getState().tasks;
    expect(Object.keys(tasks)).toHaveLength(1);
    expect(tasks["wf-test-1"].pipeline).toBe("index_repo");
    expect(tasks["wf-test-1"].status).toBe("running");
  });

  it("processEvent ignores non-background pipelines", () => {
    useTaskStore.getState().processEvent(makeEvent({ pipeline: "agent" }));
    expect(Object.keys(useTaskStore.getState().tasks)).toHaveLength(0);

    useTaskStore.getState().processEvent(makeEvent({ pipeline: "query" }));
    expect(Object.keys(useTaskStore.getState().tasks)).toHaveLength(0);
  });

  it("processEvent updates current step on step events", () => {
    useTaskStore.getState().processEvent(makeEvent());
    useTaskStore.getState().processEvent(
      makeEvent({ step: "clone_or_pull", status: "started", detail: "Cloning..." })
    );
    const task = useTaskStore.getState().tasks["wf-test-1"];
    expect(task.currentStep).toBe("clone_or_pull");
    expect(task.currentStepDetail).toBe("Cloning...");
  });

  it("processEvent updates step even when pipeline field is empty (already tracked)", () => {
    useTaskStore.getState().processEvent(makeEvent());
    useTaskStore.getState().processEvent(
      makeEvent({ step: "analyze_files", status: "started", detail: "Analyzing...", pipeline: "" })
    );
    const task = useTaskStore.getState().tasks["wf-test-1"];
    expect(task.currentStep).toBe("analyze_files");
    expect(task.pipeline).toBe("index_repo");
  });

  it("processEvent marks completed on pipeline_end", () => {
    useTaskStore.getState().processEvent(makeEvent());
    useTaskStore.getState().processEvent(
      makeEvent({ step: "pipeline_end", status: "completed", detail: "Done" })
    );
    const task = useTaskStore.getState().tasks["wf-test-1"];
    expect(task.status).toBe("completed");
    expect(task.completedAt).toBeDefined();
  });

  it("processEvent marks failed on pipeline_end with failed status", () => {
    useTaskStore.getState().processEvent(makeEvent());
    useTaskStore.getState().processEvent(
      makeEvent({ step: "pipeline_end", status: "failed", detail: "LLM error" })
    );
    const task = useTaskStore.getState().tasks["wf-test-1"];
    expect(task.status).toBe("failed");
    expect(task.error).toBe("LLM error");
  });

  it("completed tasks auto-dismiss after 5s", () => {
    useTaskStore.getState().processEvent(makeEvent());
    useTaskStore.getState().processEvent(
      makeEvent({ step: "pipeline_end", status: "completed" })
    );
    expect(Object.keys(useTaskStore.getState().tasks)).toHaveLength(1);

    vi.advanceTimersByTime(5001);
    expect(Object.keys(useTaskStore.getState().tasks)).toHaveLength(0);
  });

  it("failed tasks auto-dismiss after 30s", () => {
    useTaskStore.getState().processEvent(makeEvent());
    useTaskStore.getState().processEvent(
      makeEvent({ step: "pipeline_end", status: "failed" })
    );
    vi.advanceTimersByTime(5001);
    expect(Object.keys(useTaskStore.getState().tasks)).toHaveLength(1);

    vi.advanceTimersByTime(25001);
    expect(Object.keys(useTaskStore.getState().tasks)).toHaveLength(0);
  });

  it("dismissTask removes task immediately", () => {
    useTaskStore.getState().processEvent(makeEvent());
    useTaskStore.getState().dismissTask("wf-test-1");
    expect(Object.keys(useTaskStore.getState().tasks)).toHaveLength(0);
  });

  it("seedFromApi adds tasks without overwriting existing", () => {
    useTaskStore.getState().processEvent(makeEvent());

    useTaskStore.getState().seedFromApi([
      { workflow_id: "wf-test-1", pipeline: "index_repo", started_at: 1000, extra: {} },
      { workflow_id: "wf-new", pipeline: "db_index", started_at: 2000, extra: { connection_id: "c1" } },
    ]);

    const tasks = useTaskStore.getState().tasks;
    expect(Object.keys(tasks)).toHaveLength(2);
    expect(tasks["wf-test-1"].extra.project_id).toBe("p1");
    expect(tasks["wf-new"].pipeline).toBe("db_index");
  });

  it("processEvent creates task from step event if pipeline_start was missed but pipeline is known", () => {
    useTaskStore.getState().processEvent(
      makeEvent({ step: "analyze_files", status: "started", detail: "Analyzing...", pipeline: "index_repo" })
    );
    const task = useTaskStore.getState().tasks["wf-test-1"];
    expect(task).toBeDefined();
    expect(task.status).toBe("running");
    expect(task.currentStep).toBe("analyze_files");
  });

  it("processEvent ignores step event with empty pipeline for unknown workflow", () => {
    useTaskStore.getState().processEvent(
      makeEvent({ step: "analyze_files", status: "started", detail: "Analyzing...", pipeline: "" })
    );
    expect(Object.keys(useTaskStore.getState().tasks)).toHaveLength(0);
  });

  it("pipeline_end without prior tracking is ignored", () => {
    useTaskStore.getState().processEvent(
      makeEvent({ step: "pipeline_end", status: "completed", detail: "Done" })
    );
    expect(Object.keys(useTaskStore.getState().tasks)).toHaveLength(0);
  });
});
