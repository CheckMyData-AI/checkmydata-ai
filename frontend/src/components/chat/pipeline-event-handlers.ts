import type { PipelineStage } from "./pipeline-types";
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

function previewFromExtra(extra: ExtraBag) {
  const columns = extra.columns as string[] | undefined;
  const sampleRows = (extra.sample_rows as unknown[][]) ?? undefined;
  const summary = extra.summary as string | undefined;
  const rowCount = extra.row_count as number | undefined;
  if (!columns && !sampleRows && !summary && rowCount === undefined) return undefined;
  return { columns, sampleRows, summary, rowCount };
}

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
          prev.map((s) =>
            s.id === sid ? { ...s, status: "running", dataGateDetail: undefined } : s,
          ),
      };
    }
    case "stage_result":
    case "stage_complete": {
      const sid = extra.stage_id as string;
      const status = event.status as string;
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
                  dataGateDetail: undefined,
                }
              : s,
          ),
      };
    }
    case "stage_validation": {
      const sid = extra.stage_id as string;
      const passed = extra.passed as boolean;
      const warnings = (extra.warnings as string[]) ?? [];
      if (passed) {
        if (!warnings.length) return null;
        return {
          mapStages: (prev) =>
            prev.map((s) => (s.id === sid ? { ...s, warnings: [...(s.warnings ?? []), ...warnings] } : s)),
        };
      }
      return {
        mapStages: (prev) =>
          prev.map((s) =>
            s.id === sid
              ? {
                  ...s,
                  status: "failed",
                  warnings,
                  error: ((extra.errors as string[]) ?? []).join("; "),
                }
              : s,
          ),
      };
    }
    case "checkpoint": {
      const sid = extra.stage_id as string;
      const preview = previewFromExtra(extra);
      return {
        checkpointStageId: sid,
        mapStages: (prev) =>
          prev.map((s) =>
            s.id === sid
              ? {
                  ...s,
                  status: "checkpoint",
                  checkpointPreview: preview,
                  rowCount: preview?.rowCount ?? s.rowCount,
                  columns: preview?.columns ?? s.columns,
                }
              : s,
          ),
      };
    }
    case "stage_retry": {
      const sid = extra.stage_id as string;
      return {
        mapStages: (prev) =>
          prev.map((s) =>
            s.id === sid ? { ...s, status: "running", error: undefined, dataGateDetail: undefined } : s,
          ),
      };
    }
    case "data_gate": {
      const sid = extra.stage_id as string;
      const gateStatus = event.status as string;
      const detail = (event.detail as string) ?? "";
      if (gateStatus === "checking" || gateStatus === "started") {
        return {
          mapStages: (prev) =>
            prev.map((s) =>
              s.id === sid ? { ...s, status: "validating", dataGateDetail: detail || "Validating data…" } : s,
            ),
        };
      }
      if (gateStatus === "passed") {
        return {
          mapStages: (prev) =>
            prev.map((s) =>
              s.id === sid
                ? {
                    ...s,
                    status: s.status === "validating" ? "running" : s.status,
                    dataGateDetail: undefined,
                    warnings: (extra.warnings as string[])?.length
                      ? [...(s.warnings ?? []), ...((extra.warnings as string[]) ?? [])]
                      : s.warnings,
                  }
                : s,
            ),
        };
      }
      if (gateStatus === "failed") {
        return {
          mapStages: (prev) =>
            prev.map((s) =>
              s.id === sid
                ? {
                    ...s,
                    status: "failed",
                    dataGateDetail: undefined,
                    error: detail || ((extra.errors as string[]) ?? []).join("; "),
                    warnings: (extra.warnings as string[]) ?? s.warnings,
                  }
                : s,
            ),
        };
      }
      return null;
    }
    default:
      return null;
  }
}
