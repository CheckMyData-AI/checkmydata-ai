"use client";

import { useMemo, useState } from "react";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { CheckpointCard } from "@/components/chat/CheckpointCard";
import { StageRow } from "@/components/chat/StageRow";
import type { PipelineStage } from "@/components/chat/pipeline-types";
import { cn } from "@/lib/utils";

export type { PipelineStage, PipelineStageStatus, CheckpointPreview } from "@/components/chat/pipeline-types";

interface StageProgressProps {
  stages: PipelineStage[];
  pipelineRunId?: string;
  onContinue?: () => void;
  onModify?: (modification: string) => void;
  onRetry?: () => void;
  checkpointStageId?: string;
  compact?: boolean;
  /** Live tool-call labels rendered under the active stage */
  toolActivity?: React.ReactNode;
}

function countDone(stages: PipelineStage[]): number {
  return stages.filter((s) => s.status === "passed" || s.status === "skipped").length;
}

function currentStageIndex(stages: PipelineStage[]): number {
  const running = stages.findIndex(
    (s) =>
      s.status === "running" ||
      s.status === "checkpoint" ||
      s.status === "validating" ||
      s.status === "failed",
  );
  if (running >= 0) return running + 1;
  const done = countDone(stages);
  return done > 0 ? Math.min(done, stages.length) : 1;
}

export function StageProgress({
  stages,
  onContinue,
  onModify,
  onRetry,
  checkpointStageId,
  compact = false,
  toolActivity,
}: StageProgressProps) {
  const [showAll, setShowAll] = useState(false);

  const { total, done, currentIdx, activeId, hasFailed } = useMemo(() => {
    const t = stages.length;
    const d = countDone(stages);
    const idx = currentStageIndex(stages);
    const active =
      stages.find(
        (s) =>
          s.status === "running" ||
          s.status === "checkpoint" ||
          s.status === "validating" ||
          s.status === "failed",
      )?.id ?? stages[Math.min(d, t - 1)]?.id;
    return {
      total: t,
      done: d,
      currentIdx: idx,
      activeId: active,
      hasFailed: stages.some((s) => s.status === "failed"),
    };
  }, [stages]);

  if (!stages.length) return null;

  const checkpointStage = checkpointStageId
    ? stages.find((s) => s.id === checkpointStageId)
    : undefined;
  const actionStage =
    checkpointStage ?? stages.find((s) => s.status === "failed" || s.status === "checkpoint");
  const showCheckpointActions =
    Boolean(checkpointStageId) || hasFailed;

  return (
    <div
      className="space-y-3"
      role="status"
      aria-live="polite"
      aria-label={`Pipeline progress: stage ${currentIdx} of ${total}`}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-semibold text-text-primary">Pipeline</span>
        <span className="text-xs text-text-secondary shrink-0">
          Stage {currentIdx} of {total}
        </span>
      </div>

      <ProgressBar
        value={done}
        max={total}
        tone={hasFailed ? "error" : done === total ? "success" : "accent"}
        label={`${done} of ${total} stages complete`}
      />

      <div className="space-y-1.5">
        {stages.map((stage, index) => {
          const isCurrent = stage.id === activeId;
          const expanded = showAll || isCurrent;
          const isLast = index === stages.length - 1;

          if (!showAll && !isCurrent && stage.status !== "checkpoint") {
            if (stage.status === "pending") {
              return null;
            }
            if (stage.status === "passed" || stage.status === "skipped") {
              return (
                <StageRow
                  key={stage.id}
                  stage={stage}
                  index={index}
                  isCurrent={false}
                  expanded={false}
                  showConnector={!isLast}
                />
              );
            }
          }

          return (
            <div key={stage.id}>
              <StageRow
                stage={stage}
                index={index}
                isCurrent={isCurrent}
                expanded={expanded}
                showConnector={!isLast}
                onToggle={
                  !compact && stage.description.length > 80
                    ? () => setShowAll((v) => !v)
                    : undefined
                }
              />
              {isCurrent && toolActivity ? (
                <div className="ml-7 mt-1 mb-1">{toolActivity}</div>
              ) : null}
            </div>
          );
        })}
      </div>

      {stages.some((s) => s.status === "pending") ? (
        <button
          type="button"
          className="text-xs text-accent hover:text-accent-hover transition-colors ui-pressable"
          onClick={() => setShowAll((v) => !v)}
        >
          {showAll ? "Collapse stages" : `Show all ${total} stages`}
        </button>
      ) : null}

      {showCheckpointActions && actionStage ? (
        <CheckpointCard
          stage={actionStage}
          preview={{
            columns: actionStage.checkpointPreview?.columns ?? actionStage.columns,
            sampleRows: actionStage.checkpointPreview?.sampleRows,
            summary: actionStage.checkpointPreview?.summary,
            rowCount: actionStage.rowCount,
          }}
          onContinue={onContinue && checkpointStageId ? onContinue : undefined}
          onModify={
            onModify && (checkpointStageId || hasFailed)
              ? onModify
              : undefined
          }
          onRetry={onRetry && hasFailed ? onRetry : undefined}
        />
      ) : null}
    </div>
  );
}
