"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import type { CheckpointPreview, PipelineStage } from "@/components/chat/pipeline-types";
import { cn } from "@/lib/utils";

export interface CheckpointCardProps {
  stage: PipelineStage;
  preview?: CheckpointPreview;
  onContinue?: () => void;
  onModify?: (modification: string) => void;
  onRetry?: () => void;
  className?: string;
}

function PreviewTable({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  if (!columns.length) return null;
  const displayRows = rows.slice(0, 5);

  return (
    <div className="data-table-scroll overflow-x-auto rounded-lg border border-border-subtle mt-3">
      <table className="w-full text-xs text-left">
        <thead>
          <tr className="border-b border-border-subtle bg-surface-2">
            {columns.map((col) => (
              <th key={col} className="px-2 py-1.5 font-medium text-text-secondary whitespace-nowrap">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {displayRows.map((row, ri) => (
            <tr key={ri} className="border-b border-border-subtle/50 last:border-0">
              {columns.map((_, ci) => (
                <td key={ci} className="px-2 py-1.5 text-text-primary font-mono whitespace-nowrap max-w-[12rem] truncate">
                  {String((row as unknown[])[ci] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CheckpointCard({
  stage,
  preview,
  onContinue,
  onModify,
  onRetry,
  className,
}: CheckpointCardProps) {
  const [modifyText, setModifyText] = useState("");
  const [showModify, setShowModify] = useState(false);

  const columns = preview?.columns ?? stage.columns ?? [];
  const rows = preview?.sampleRows ?? [];
  const summary = preview?.summary ?? stage.checkpointPreview?.summary;

  return (
    <div
      className={cn(
        "checkpoint-reveal mt-3 rounded-lg border border-warning/30 bg-warning-muted/40 p-4",
        className,
      )}
      role="region"
      aria-label="Checkpoint review"
    >
      <h4 className="text-sm font-semibold text-text-primary">Review before continuing</h4>
      <p className="text-xs text-text-secondary mt-1 leading-relaxed">
        Check this step&apos;s output. Continue to run the rest of the pipeline, modify the plan, or
        retry this stage.
      </p>
      {summary ? (
        <p className="text-xs text-text-tertiary mt-2 line-clamp-3" title={summary}>
          {summary}
        </p>
      ) : null}
      {columns.length > 0 && rows.length > 0 ? (
        <PreviewTable columns={columns} rows={rows as unknown[][]} />
      ) : null}

      <div className="mt-4 flex flex-col gap-2">
        {!showModify ? (
          <div className="flex flex-wrap gap-2">
            {onContinue ? (
              <Button variant="primary" size="sm" onClick={onContinue}>
                Continue pipeline
              </Button>
            ) : null}
            {onModify ? (
              <Button variant="secondary" size="sm" onClick={() => setShowModify(true)}>
                Modify plan
              </Button>
            ) : null}
            {onRetry ? (
              <Button variant="ghost" size="sm" onClick={onRetry}>
                Retry stage
              </Button>
            ) : null}
          </div>
        ) : (
          <div className="flex flex-col sm:flex-row gap-2">
            <Input
              className="flex-1"
              value={modifyText}
              onChange={(e) => setModifyText(e.target.value)}
              placeholder="Describe what to change…"
              aria-label="Modification instructions"
              onKeyDown={(e) => {
                if (e.key === "Enter" && modifyText.trim()) {
                  onModify?.(modifyText.trim());
                  setModifyText("");
                  setShowModify(false);
                }
              }}
            />
            <div className="flex gap-2 shrink-0">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  if (modifyText.trim()) {
                    onModify?.(modifyText.trim());
                    setModifyText("");
                    setShowModify(false);
                  }
                }}
              >
                Send changes
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setShowModify(false);
                  setModifyText("");
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
