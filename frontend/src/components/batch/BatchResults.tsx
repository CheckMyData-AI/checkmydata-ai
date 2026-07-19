"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type BatchQueryDTO } from "@/lib/api";
import { toast } from "@/stores/toast-store";
import { Icon } from "@/components/ui/Icon";
import { Tooltip } from "@/components/ui/Tooltip";
import { useDialogA11y } from "@/hooks/useDialogA11y";
import { DataTable } from "@/components/viz/DataTable";

interface BatchResultsProps {
  batchId: string;
  onClose?: () => void;
  onBack?: () => void;
}

// A single per-query record inside BatchQueryDTO.results_json (see
// backend/app/services/batch_service.py). `rows` are arrays of values in
// `columns` order — DataTable keys by column name, so we map them below.
interface BatchResultEntry {
  title?: string;
  sql?: string;
  status?: "success" | "failed" | "blocked";
  columns?: string[];
  rows?: unknown[][];
  total_rows?: number;
  duration_ms?: number;
  error?: string;
}

type LoadState = "loading" | "loaded" | "error";

const RUNNING_STATUSES = new Set(["pending", "running"]);

function parseEntries(json: string | null): BatchResultEntry[] {
  if (!json) return [];
  try {
    const parsed = JSON.parse(json);
    return Array.isArray(parsed) ? (parsed as BatchResultEntry[]) : [];
  } catch {
    return [];
  }
}

function sanitizeFilename(name: string): string {
  return (name || "batch").replace(/[^a-z0-9._-]+/gi, "_").slice(0, 80);
}

export function BatchResults({ batchId, onClose, onBack }: BatchResultsProps) {
  const [state, setState] = useState<LoadState>("loading");
  const [batch, setBatch] = useState<BatchQueryDTO | null>(null);
  const [entries, setEntries] = useState<BatchResultEntry[]>([]);
  const [exporting, setExporting] = useState(false);
  const mountedRef = useRef(true);
  const panelRef = useRef<HTMLDivElement>(null);

  useDialogA11y({ open: true, onClose: () => onClose?.(), panelRef });

  const load = useCallback(async () => {
    setState("loading");
    try {
      const dto = await api.batch.get(batchId);
      if (!mountedRef.current) return;
      setBatch(dto);
      setEntries(parseEntries(dto.results_json));
      setState("loaded");
    } catch {
      if (!mountedRef.current) return;
      setState("error");
    }
  }, [batchId]);

  useEffect(() => {
    mountedRef.current = true;
    load();
    return () => {
      mountedRef.current = false;
    };
  }, [load]);

  const handleExport = useCallback(async () => {
    setExporting(true);
    try {
      const blob = await api.batch.export(batchId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${sanitizeFilename(batch?.title ?? `batch_${batchId}`)}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to export batch", "error");
    } finally {
      if (mountedRef.current) setExporting(false);
    }
  }, [batchId, batch?.title]);

  const isRunning = batch ? RUNNING_STATUSES.has(batch.status) : false;
  const hasEntries = entries.length > 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose?.();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Batch Results"
        className="bg-surface-0 border border-border-subtle rounded-lg w-full max-w-2xl max-h-[85vh] flex flex-col mx-4 shadow-xl animate-in fade-in zoom-in-95 duration-150"
      >
        {/* Header */}
        <div className="shrink-0 px-5 py-4 border-b border-border-subtle flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 min-w-0">
            {onBack && (
              <Tooltip label="Back to runner">
                <button
                  onClick={onBack}
                  aria-label="Back to runner"
                  className="p-1.5 rounded text-text-muted hover:text-text-secondary hover:bg-surface-2 transition-colors shrink-0"
                >
                  <Icon name="arrow-left" size={14} />
                </button>
              </Tooltip>
            )}
            <Icon name="layers" size={16} className="text-accent shrink-0" />
            <h2 className="text-sm font-semibold text-text-primary truncate">
              {batch?.title || "Batch Results"}
            </h2>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={handleExport}
              disabled={exporting || !hasEntries}
              className="flex items-center gap-1 text-[11px] px-3 py-1.5 rounded border border-border-default text-text-secondary hover:text-text-primary hover:bg-surface-2 transition-colors disabled:opacity-40"
            >
              <Icon name={exporting ? "refresh-cw" : "download"} size={11} className={exporting ? "animate-spin" : ""} />
              Export
            </button>
            {onClose && (
              <Tooltip label="Close">
                <button
                  onClick={onClose}
                  aria-label="Close batch results"
                  className="p-1.5 rounded text-text-muted hover:text-text-secondary hover:bg-surface-2 transition-colors"
                >
                  <Icon name="x" size={14} />
                </button>
              </Tooltip>
            )}
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4 sidebar-scroll">
          {state === "loading" ? (
            <div className="flex justify-center py-10" role="status" aria-live="polite">
              <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" />
              <span className="sr-only">Loading batch results</span>
            </div>
          ) : state === "error" ? (
            <div className="flex flex-col items-center gap-3 py-10 text-center">
              <Icon name="alert-triangle" size={20} className="text-error" />
              <p className="text-xs text-text-secondary">Couldn&apos;t load batch results</p>
              <button
                onClick={load}
                className="flex items-center gap-1 text-[11px] px-3 py-1.5 rounded border border-border-default text-text-secondary hover:text-text-primary hover:bg-surface-2 transition-colors"
              >
                <Icon name="refresh-cw" size={11} />
                Retry
              </button>
            </div>
          ) : !hasEntries ? (
            <div className="flex flex-col items-center gap-2 py-10 text-center">
              <Icon name={isRunning ? "clock" : "layers"} size={20} className="text-text-muted" />
              <p className="text-xs text-text-secondary">
                {isRunning ? "Batch is still running — no results yet." : "No results for this batch."}
              </p>
            </div>
          ) : (
            entries.map((entry, idx) => {
              const title = entry.title || `Query ${idx + 1}`;
              const isSuccess = entry.status === "success";
              if (isSuccess) {
                const columns = entry.columns ?? [];
                const rowObjects = (entry.rows ?? []).map((row) =>
                  Object.fromEntries(columns.map((col, i) => [col, row[i]])),
                );
                return (
                  <div key={idx} className="space-y-1.5">
                    <div className="flex items-center gap-2">
                      <Icon name="check" size={12} className="text-success shrink-0" />
                      <span className="text-xs font-medium text-text-primary truncate flex-1">{title}</span>
                    </div>
                    <DataTable
                      data={{
                        columns,
                        rows: rowObjects,
                        total_rows: entry.total_rows ?? rowObjects.length,
                        execution_time_ms: entry.duration_ms,
                      }}
                    />
                  </div>
                );
              }
              return (
                <div
                  key={idx}
                  className="bg-surface-1 border border-error/30 rounded-lg p-3 space-y-1.5"
                >
                  <div className="flex items-center gap-2">
                    <Icon name="alert-triangle" size={12} className="text-error shrink-0" />
                    <span className="text-xs font-medium text-text-primary truncate flex-1">{title}</span>
                    <span className="text-[10px] font-mono text-error uppercase shrink-0">
                      {entry.status || "failed"}
                    </span>
                  </div>
                  <p className="text-[11px] text-error/90 leading-relaxed break-words">
                    {entry.error || "Query failed with no error detail."}
                  </p>
                  {entry.sql && (
                    <pre className="text-[10px] font-mono text-text-muted bg-surface-0 border border-border-subtle rounded px-2.5 py-2 overflow-x-auto whitespace-pre-wrap">
                      {entry.sql}
                    </pre>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
