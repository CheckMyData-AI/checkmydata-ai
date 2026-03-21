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
  pending: "text-zinc-500",
  running: "text-blue-400",
  passed: "text-emerald-400",
  failed: "text-red-400",
  checkpoint: "text-amber-400",
  skipped: "text-zinc-600",
};

const STATUS_BG: Record<string, string> = {
  pending: "bg-zinc-800",
  running: "bg-blue-900/30 border-blue-700/30",
  passed: "bg-emerald-900/20 border-emerald-700/20",
  failed: "bg-red-900/20 border-red-700/20",
  checkpoint: "bg-amber-900/20 border-amber-700/20",
  skipped: "bg-zinc-800/50",
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
      <div className="flex items-center justify-between text-xs text-zinc-400 mb-1">
        <span className="font-medium">Pipeline Progress</span>
        <span>
          {done}/{total} stages
        </span>
      </div>

      <div className="space-y-1.5">
        {stages.map((stage, idx) => (
          <div
            key={stage.id}
            className={`flex items-start gap-2 px-3 py-2 rounded-lg border text-sm ${STATUS_BG[stage.status] || "bg-zinc-800"}`}
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
                <div className="w-px h-3 bg-zinc-700 mt-1" />
              )}
            </div>

            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span
                  className={`font-medium truncate ${
                    stage.status === "pending" ? "text-zinc-500" : "text-zinc-200"
                  }`}
                >
                  {stage.description}
                </span>
                {!compact && (
                  <span className="text-[10px] text-zinc-600 shrink-0">{stage.tool}</span>
                )}
              </div>

              {stage.status === "passed" && (stage.rowCount !== undefined || stage.columns) && !compact && (
                <div className="text-xs text-zinc-500 mt-0.5">
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
                <div className="text-xs text-red-400/80 mt-0.5 truncate">{stage.error}</div>
              )}

              {stage.warnings && stage.warnings.length > 0 && (
                <div className="text-xs text-amber-400/70 mt-0.5">
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
                  className="px-3 py-1.5 text-xs font-medium bg-emerald-600 hover:bg-emerald-500 text-white rounded-md transition-colors"
                >
                  Continue
                </button>
              )}
              {onModify && (
                <button
                  onClick={() => setShowModify(true)}
                  className="px-3 py-1.5 text-xs font-medium bg-amber-600 hover:bg-amber-500 text-white rounded-md transition-colors"
                >
                  Modify
                </button>
              )}
              {onRetry && (
                <button
                  onClick={onRetry}
                  className="px-3 py-1.5 text-xs font-medium bg-zinc-600 hover:bg-zinc-500 text-white rounded-md transition-colors"
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
                className="flex-1 px-3 py-1.5 text-xs bg-zinc-800 border border-zinc-700 rounded-md text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-amber-600"
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
                className="px-3 py-1.5 text-xs font-medium bg-amber-600 hover:bg-amber-500 text-white rounded-md transition-colors"
              >
                Send
              </button>
              <button
                onClick={() => {
                  setShowModify(false);
                  setModifyText("");
                }}
                className="px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-300"
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
