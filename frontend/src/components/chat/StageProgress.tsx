"use client";

import { useState } from "react";

export interface PipelineStage {
  id: string;
  description: string;
  tool: string;
  checkpoint: boolean;
  status: "pending" | "running" | "passed" | "failed" | "checkpoint" | "skipped";
  rowCount?: number;
  columns?: string[];
  error?: string;
  warnings?: string[];
}

interface StageProgressProps {
  stages: PipelineStage[];
  pipelineRunId?: string;
  onContinue?: () => void;
  onModify?: (modification: string) => void;
  onRetry?: () => void;
  checkpointStageId?: string;
  compact?: boolean;
}

const STATUS_ICON: Record<string, string> = {
  pending: "○",
  running: "◎",
  passed: "✓",
  failed: "✗",
  checkpoint: "◉",
  skipped: "–",
};

const STATUS_COLOR: Record<string, string> = {
  pending: "text-text-tertiary",
  running: "text-accent",
  passed: "text-success",
  failed: "text-error",
  checkpoint: "text-warning",
  skipped: "text-text-muted",
};

const STATUS_BG: Record<string, string> = {
  pending: "bg-surface-2",
  running: "bg-accent-muted border-border-default",
  passed: "bg-success-muted border-border-default",
  failed: "bg-error-muted border-border-default",
  checkpoint: "bg-warning-muted border-border-default",
  skipped: "bg-surface-2/50",
};

export function StageProgress({
  stages,
  pipelineRunId,
  onContinue,
  onModify,
  onRetry,
  checkpointStageId,
  compact = false,
}: StageProgressProps) {
  const [modifyText, setModifyText] = useState("");
  const [showModify, setShowModify] = useState(false);

  if (!stages.length) return null;

  const total = stages.length;
  const done = stages.filter((s) => s.status === "passed" || s.status === "skipped").length;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs text-text-secondary mb-1">
        <span className="font-medium">Pipeline Progress</span>
        <span>
          {done}/{total} stages
        </span>
      </div>

      <div className="space-y-1.5">
        {stages.map((stage, idx) => (
          <div
            key={stage.id}
            className={`flex items-start gap-2 px-3 py-2 rounded-lg border text-sm ${STATUS_BG[stage.status] || "bg-surface-2"}`}
          >
            <div className="flex flex-col items-center pt-0.5">
              <span className={`text-base leading-none font-mono ${STATUS_COLOR[stage.status]}`}>
                {stage.status === "running" ? (
                  <span className="inline-block animate-spin">⟳</span>
                ) : (
                  STATUS_ICON[stage.status]
                )}
              </span>
              {idx < stages.length - 1 && (
                <div className="w-px h-3 bg-surface-3 mt-1" />
              )}
            </div>

            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span
                  className={`font-medium truncate ${
                    stage.status === "pending" ? "text-text-tertiary" : "text-text-primary"
                  }`}
                  title={stage.description}
                >
                  {stage.description}
                </span>
                {!compact && (
                  <span className="text-[10px] text-text-muted shrink-0">{stage.tool}</span>
                )}
              </div>

              {stage.status === "passed" && (stage.rowCount !== undefined || stage.columns) && !compact && (
                <div className="text-xs text-text-tertiary mt-0.5">
                  {stage.rowCount !== undefined && <span>{stage.rowCount} rows</span>}
                  {stage.columns && (
                    <span className="ml-2 truncate">
                      ({stage.columns.slice(0, 4).join(", ")}
                      {stage.columns.length > 4 && ` +${stage.columns.length - 4}`})
                    </span>
                  )}
                </div>
              )}

              {stage.status === "failed" && stage.error && (
                <div className="text-xs text-error/80 mt-0.5 truncate" title={stage.error}>{stage.error}</div>
              )}

              {stage.warnings && stage.warnings.length > 0 && (
                <div className="text-xs text-warning/70 mt-0.5 break-words">
                  {stage.warnings.join("; ")}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Checkpoint / failed action buttons */}
      {(checkpointStageId || stages.some((s) => s.status === "failed")) && (
        <div className="mt-3 flex flex-col gap-2">
          {!showModify ? (
            <div className="flex gap-2">
              {onContinue && checkpointStageId && (
                <button
                  onClick={onContinue}
                  className="px-3 py-1.5 text-xs font-medium bg-success hover:bg-success text-white rounded-md transition-colors"
                >
                  Continue
                </button>
              )}
              {onModify && (
                <button
                  onClick={() => setShowModify(true)}
                  className="px-3 py-1.5 text-xs font-medium bg-warning hover:bg-warning text-white rounded-md transition-colors"
                >
                  Modify
                </button>
              )}
              {onRetry && (
                <button
                  onClick={onRetry}
                  className="px-3 py-1.5 text-xs font-medium bg-surface-3 hover:bg-surface-3/80 text-white rounded-md transition-colors"
                >
                  Retry
                </button>
              )}
            </div>
          ) : (
            <div className="flex gap-2">
              <input
                type="text"
                value={modifyText}
                onChange={(e) => setModifyText(e.target.value)}
                placeholder="Describe what to change…"
                className="flex-1 px-3 py-1.5 text-xs bg-surface-2 border border-border-default rounded-md text-text-primary placeholder-text-muted focus:outline-none focus:border-warning"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && modifyText.trim()) {
                    onModify?.(modifyText.trim());
                    setModifyText("");
                    setShowModify(false);
                  }
                }}
              />
              <button
                onClick={() => {
                  if (modifyText.trim()) {
                    onModify?.(modifyText.trim());
                    setModifyText("");
                    setShowModify(false);
                  }
                }}
                className="px-3 py-1.5 text-xs font-medium bg-warning hover:bg-warning text-white rounded-md transition-colors"
              >
                Send
              </button>
              <button
                onClick={() => {
                  setShowModify(false);
                  setModifyText("");
                }}
                className="px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
