import type { PipelineStage } from "./StageProgress";
import type { PlanSummaryData } from "./PlanSummaryCard";

// Pure helpers for ChatPanel pipeline-event handling (T29). Keeping these
// out of the component file shrinks the render closure and makes event
// transitions unit-testable.

type StageListUpdate = (stages: PipelineStage[]) => PipelineStage[];

export interface PipelineTransition {
  planSummary?: PlanSummaryData;
  setStages?: PipelineStage[];
  mapStages?: StageListUpdate;
  checkpointStageId?: string;
}

type ExtraBag = Record<string, unknown>;

export function pipelineEventToTransition(
  eventType: string,
  event: Record<string, unknown>,
): PipelineTransition | null {
  const extra = (event.extra ?? {}) as ExtraBag;
  switch (eventType) {
    case "plan_summary":
      return {
        planSummary: {
          tables: (extra.tables as string[]) ?? [],
          strategy: (extra.strategy as string) ?? "single_query",
          rules_applied: (extra.rules_applied as string[]) ?? [],
          learnings_applied: (extra.learnings_applied as string[]) ?? [],
          has_warnings: (extra.has_warnings as boolean) ?? false,
        },
      };
    case "plan": {
      const rawStages = (extra.stages ?? []) as Array<{
        id: string;
        description: string;
        tool: string;
        checkpoint: boolean;
      }>;
      return {
        setStages: rawStages.map((s) => ({
          id: s.id,
          description: s.description,
          tool: s.tool,
          checkpoint: s.checkpoint,
          status: "pending" as const,
        })),
      };
    }
    case "stage_start": {
      const sid = extra.stage_id as string;
      return {
        mapStages: (prev) =>
          prev.map((s) => (s.id === sid ? { ...s, status: "running" } : s)),
      };
    }
    case "stage_result":
    case "stage_complete": {
      const sid = extra.stage_id as string;
      const status = extra.status as string;
      return {
        mapStages: (prev) =>
          prev.map((s) =>
            s.id === sid
              ? {
                  ...s,
                  status: status === "error" ? "failed" : "passed",
                  rowCount: (extra.row_count as number) ?? s.rowCount,
                  columns: (extra.columns as string[]) ?? s.columns,
                  error: (extra.error as string) ?? undefined,
                }
              : s,
          ),
      };
    }
    case "stage_validation": {
      const sid = extra.stage_id as string;
      const passed = extra.passed as boolean;
      if (passed) return null;
      return {
        mapStages: (prev) =>
          prev.map((s) =>
            s.id === sid
              ? {
                  ...s,
                  status: "failed",
                  warnings: (extra.warnings as string[]) ?? [],
                  error: ((extra.errors as string[]) ?? []).join("; "),
                }
              : s,
          ),
      };
    }
    case "checkpoint": {
      const sid = extra.stage_id as string;
      return {
        checkpointStageId: sid,
        mapStages: (prev) =>
          prev.map((s) => (s.id === sid ? { ...s, status: "checkpoint" } : s)),
      };
    }
    case "stage_retry": {
      const sid = extra.stage_id as string;
      return {
        mapStages: (prev) =>
          prev.map((s) => (s.id === sid ? { ...s, status: "running" } : s)),
      };
    }
    default:
      return null;
  }
}
