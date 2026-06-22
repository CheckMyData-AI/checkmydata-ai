import { describe, it, expect } from "vitest";
import type { WorkflowEvent } from "@/lib/sse";
import type { RunTask, ErrorLogItem } from "@/lib/api/types";
import { api } from "@/lib/api";

describe("run/observability contracts", () => {
  it("WorkflowEvent carries progress fields", () => {
    const ev: WorkflowEvent = {
      workflow_id: "w",
      step: "s",
      status: "started",
      detail: "",
      elapsed_ms: null,
      timestamp: 0,
      pipeline: "db_index",
      extra: {},
      run_id: "r",
      kind: "db_index",
      step_index: 2,
      total_steps: 6,
      progress_pct: 33,
    };
    expect(ev.progress_pct).toBe(33);
  });

  it("RunTask + ErrorLogItem shapes exist", () => {
    const t: RunTask = {
      runId: "r",
      workflowId: "w",
      kind: "db_index",
      status: "running",
      projectId: "p",
      connectionId: "c",
      currentStep: "x",
      stepIndex: 1,
      totalSteps: 6,
      progressPct: 16,
      startedAt: 0,
      source: "sse",
    };
    const e: ErrorLogItem = {
      id: "e",
      source: "run",
      kind: "db_index",
      failure_kind: "fatal",
      message: "x",
      occurrences: 1,
      status: "open",
      sample_ref: "r",
      first_seen_at: null,
      last_seen_at: null,
    };
    expect(t.progressPct).toBe(16);
    expect(e.status).toBe("open");
  });

  it("api exposes runs + logs namespaces", () => {
    expect(typeof api.runs.cancel).toBe("function");
    expect(typeof api.runs.retry).toBe("function");
    expect(typeof api.logs.errors).toBe("function");
    expect(typeof api.logs.runs).toBe("function");
  });
});
