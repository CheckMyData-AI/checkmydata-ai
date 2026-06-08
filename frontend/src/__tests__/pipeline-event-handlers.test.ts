import { describe, expect, it } from "vitest";

import { pipelineEventToTransition } from "@/components/chat/pipeline-event-handlers";
import type { PipelineStage } from "@/components/chat/StageProgress";

const stage = (id: string, status: PipelineStage["status"]): PipelineStage => ({
  id,
  description: id,
  tool: "sql",
  checkpoint: false,
  status,
});

describe("pipelineEventToTransition", () => {
  it("returns plan_summary payload", () => {
    const t = pipelineEventToTransition("plan_summary", {
      extra: {
        tables: ["users", "orders"],
        strategy: "pipeline",
        rules_applied: ["r1"],
        learnings_applied: ["l1"],
        has_warnings: true,
      },
    });
    expect(t?.planSummary).toEqual({
      tables: ["users", "orders"],
      strategy: "pipeline",
      rules_applied: ["r1"],
      learnings_applied: ["l1"],
      has_warnings: true,
    });
  });

  it("plan_summary uses defaults when extra is missing", () => {
    const t = pipelineEventToTransition("plan_summary", {});
    expect(t?.planSummary).toEqual({
      tables: [],
      strategy: "single_query",
      rules_applied: [],
      learnings_applied: [],
      has_warnings: false,
    });
  });

  it("plan event maps incoming stage descriptors to pending stages", () => {
    const t = pipelineEventToTransition("plan", {
      extra: {
        stages: [
          { id: "s1", description: "load", tool: "sql", checkpoint: false },
          { id: "s2", description: "viz", tool: "viz", checkpoint: true },
        ],
      },
    });
    expect(t?.setStages).toEqual([
      {
        id: "s1",
        description: "load",
        tool: "sql",
        checkpoint: false,
        status: "pending",
      },
      {
        id: "s2",
        description: "viz",
        tool: "viz",
        checkpoint: true,
        status: "pending",
      },
    ]);
  });

  it("stage_start moves the matching stage to running", () => {
    const t = pipelineEventToTransition("stage_start", {
      extra: { stage_id: "s1" },
    });
    const next = t?.mapStages?.([stage("s1", "pending"), stage("s2", "pending")]);
    expect(next).toEqual([stage("s1", "running"), stage("s2", "pending")]);
  });

  it("stage_complete with error marks stage as failed", () => {
    // status lives on the top-level event, not in extra
    const t = pipelineEventToTransition("stage_complete", {
      status: "error",
      extra: { stage_id: "s1", error: "boom" },
    });
    const [updated] = t?.mapStages?.([stage("s1", "running")]) ?? [];
    expect(updated.status).toBe("failed");
    expect(updated.error).toBe("boom");
  });

  it("stage_complete success copies row metadata", () => {
    const t = pipelineEventToTransition("stage_complete", {
      status: "ok",
      extra: {
        stage_id: "s1",
        row_count: 42,
        columns: ["id"],
      },
    });
    const [updated] = t?.mapStages?.([stage("s1", "running")]) ?? [];
    expect(updated.status).toBe("passed");
    expect(updated.rowCount).toBe(42);
    expect(updated.columns).toEqual(["id"]);
  });

  it("stage_result reads status from the top-level event", () => {
    const t = pipelineEventToTransition("stage_result", {
      status: "error",
      extra: { stage_id: "s1", error: "boom" },
    });
    const [updated] = t?.mapStages?.([stage("s1", "running")]) ?? [];
    expect(updated.status).toBe("failed");
    expect(updated.error).toBe("boom");
  });

  it("stage_validation passing returns null (no transition)", () => {
    const t = pipelineEventToTransition("stage_validation", {
      extra: { stage_id: "s1", passed: true },
    });
    expect(t).toBeNull();
  });

  it("stage_validation failing fails the stage with errors joined", () => {
    const t = pipelineEventToTransition("stage_validation", {
      extra: {
        stage_id: "s1",
        passed: false,
        errors: ["a", "b"],
        warnings: ["w"],
      },
    });
    const [updated] = t?.mapStages?.([stage("s1", "running")]) ?? [];
    expect(updated.status).toBe("failed");
    expect(updated.error).toBe("a; b");
    expect(updated.warnings).toEqual(["w"]);
  });

  it("checkpoint event records the stage id and marks stage as checkpoint", () => {
    const t = pipelineEventToTransition("checkpoint", {
      extra: { stage_id: "s2" },
    });
    expect(t?.checkpointStageId).toBe("s2");
    const [s1, s2] = t?.mapStages?.([stage("s1", "running"), stage("s2", "running")]) ?? [];
    expect(s1.status).toBe("running");
    expect(s2.status).toBe("checkpoint");
  });

  it("stage_retry resets the stage to running", () => {
    const t = pipelineEventToTransition("stage_retry", {
      extra: { stage_id: "s1" },
    });
    const [updated] = t?.mapStages?.([stage("s1", "failed")]) ?? [];
    expect(updated.status).toBe("running");
  });

  it("unknown event types are no-ops", () => {
    expect(pipelineEventToTransition("unknown_event", {})).toBeNull();
  });
});
