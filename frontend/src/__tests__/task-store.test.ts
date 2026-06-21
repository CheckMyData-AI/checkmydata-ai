import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { useBackgroundTasks } from "@/stores/background-tasks-store";
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
  useBackgroundTasks.setState({ tasks: {} });
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("background-tasks-store (legacy task-store coverage)", () => {
  it("applySseEvent creates task on pipeline_start", () => {
    useBackgroundTasks.getState().applySseEvent(makeEvent());
    const tasks = useBackgroundTasks.getState().tasks;
    expect(Object.keys(tasks)).toHaveLength(1);
    expect(tasks["wf-test-1"].pipeline).toBe("index_repo");
    expect(tasks["wf-test-1"].status).toBe("running");
  });

  it("applySseEvent ignores non-background pipelines", () => {
    useBackgroundTasks.getState().applySseEvent(makeEvent({ pipeline: "agent" }));
    expect(Object.keys(useBackgroundTasks.getState().tasks)).toHaveLength(0);

    useBackgroundTasks.getState().applySseEvent(makeEvent({ pipeline: "query" }));
    expect(Object.keys(useBackgroundTasks.getState().tasks)).toHaveLength(0);
  });

  it("applySseEvent updates current step on step events", () => {
    useBackgroundTasks.getState().applySseEvent(makeEvent());
    useBackgroundTasks.getState().applySseEvent(
      makeEvent({ step: "clone_or_pull", status: "started", detail: "Cloning..." })
    );
    const task = useBackgroundTasks.getState().tasks["wf-test-1"];
    expect(task.currentStep).toBe("clone_or_pull");
    expect(task.currentStepDetail).toBe("Cloning...");
  });

  it("applySseEvent updates step even when pipeline field is empty (already tracked)", () => {
    useBackgroundTasks.getState().applySseEvent(makeEvent());
    useBackgroundTasks.getState().applySseEvent(
      makeEvent({ step: "analyze_files", status: "started", detail: "Analyzing...", pipeline: "" })
    );
    const task = useBackgroundTasks.getState().tasks["wf-test-1"];
    expect(task.currentStep).toBe("analyze_files");
    expect(task.pipeline).toBe("index_repo");
  });

  it("applySseEvent marks completed on pipeline_end", () => {
    useBackgroundTasks.getState().applySseEvent(makeEvent());
    useBackgroundTasks.getState().applySseEvent(
      makeEvent({ step: "pipeline_end", status: "completed", detail: "Done" })
    );
    const task = useBackgroundTasks.getState().tasks["wf-test-1"];
    expect(task.status).toBe("completed");
    expect(task.completedAt).toBeDefined();
  });

  it("applySseEvent marks failed on pipeline_end with failed status", () => {
    useBackgroundTasks.getState().applySseEvent(makeEvent());
    useBackgroundTasks.getState().applySseEvent(
      makeEvent({ step: "pipeline_end", status: "failed", detail: "LLM error" })
    );
    const task = useBackgroundTasks.getState().tasks["wf-test-1"];
    expect(task.status).toBe("failed");
    expect(task.error).toBe("LLM error");
  });

  it("completed tasks auto-dismiss after 5s", () => {
    useBackgroundTasks.getState().applySseEvent(makeEvent());
    useBackgroundTasks.getState().applySseEvent(
      makeEvent({ step: "pipeline_end", status: "completed" })
    );
    expect(Object.keys(useBackgroundTasks.getState().tasks)).toHaveLength(1);

    vi.advanceTimersByTime(5001);
    expect(Object.keys(useBackgroundTasks.getState().tasks)).toHaveLength(0);
  });

  it("failed tasks auto-dismiss after 30s", () => {
    useBackgroundTasks.getState().applySseEvent(makeEvent());
    useBackgroundTasks.getState().applySseEvent(
      makeEvent({ step: "pipeline_end", status: "failed" })
    );
    vi.advanceTimersByTime(5001);
    expect(Object.keys(useBackgroundTasks.getState().tasks)).toHaveLength(1);

    vi.advanceTimersByTime(25001);
    expect(Object.keys(useBackgroundTasks.getState().tasks)).toHaveLength(0);
  });

  it("dismissTask removes task immediately", () => {
    useBackgroundTasks.getState().applySseEvent(makeEvent());
    useBackgroundTasks.getState().dismissTask("wf-test-1");
    expect(Object.keys(useBackgroundTasks.getState().tasks)).toHaveLength(0);
  });

  it("reconcileFromActive adds tasks without overwriting existing SSE-running task", () => {
    useBackgroundTasks.getState().applySseEvent(makeEvent());

    useBackgroundTasks.getState().reconcileFromActive([
      { workflow_id: "wf-test-1", pipeline: "index_repo", started_at: 1000, extra: {} },
      { workflow_id: "wf-new", pipeline: "db_index", started_at: 2000, extra: { connection_id: "c1" } },
    ]);

    const tasks = useBackgroundTasks.getState().tasks;
    expect(Object.keys(tasks)).toHaveLength(2);
    expect(tasks["wf-test-1"].extra.project_id).toBe("p1");
    expect(tasks["wf-new"].pipeline).toBe("db_index");
  });

  it("applySseEvent creates task from step event if pipeline_start was missed but pipeline is known", () => {
    useBackgroundTasks.getState().applySseEvent(
      makeEvent({ step: "analyze_files", status: "started", detail: "Analyzing...", pipeline: "index_repo" })
    );
    const task = useBackgroundTasks.getState().tasks["wf-test-1"];
    expect(task).toBeDefined();
    expect(task.status).toBe("running");
    expect(task.currentStep).toBe("analyze_files");
  });

  it("applySseEvent ignores step event with empty pipeline for unknown workflow", () => {
    useBackgroundTasks.getState().applySseEvent(
      makeEvent({ step: "analyze_files", status: "started", detail: "Analyzing...", pipeline: "" })
    );
    expect(Object.keys(useBackgroundTasks.getState().tasks)).toHaveLength(0);
  });

  it("pipeline_end without prior tracking is ignored", () => {
    useBackgroundTasks.getState().applySseEvent(
      makeEvent({ step: "pipeline_end", status: "completed", detail: "Done" })
    );
    expect(Object.keys(useBackgroundTasks.getState().tasks)).toHaveLength(0);
  });
});
