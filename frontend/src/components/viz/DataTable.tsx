"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { toast } from "@/stores/toast-store";

interface DataTableProps {
  data: Record<string, unknown>;
}

const MAX_RENDERED_ROWS = 500;

export function DataTable({ data }: DataTableProps) {
  const columns = (data.columns as string[]) || [];
  const allRows = (data.rows as Record<string, unknown>[]) || [];
  const totalRows = (data.total_rows as number) || allRows.length;
  const executionTime = data.execution_time_ms as number | undefined;
  const [exporting, setExporting] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const isCapped = allRows.length > MAX_RENDERED_ROWS && !showAll;
  const rows = isCapped ? allRows.slice(0, MAX_RENDERED_ROWS) : allRows;

  const handleExport = async (format: string) => {
    setExporting(true);
    try {
      const rawRows = rows.map((row) => columns.map((col) => row[col]));
      const blob = await api.viz.export(columns, rawRows, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `export.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Export failed", "error");
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="bg-surface-1 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-border-subtle">
        <span className="text-xs text-text-secondary">
          {totalRows} row{totalRows !== 1 ? "s" : ""}
          {executionTime != null && ` • ${executionTime.toFixed(0)}ms`}
        </span>
        <div className="flex gap-2">
          {["csv", "json", "xlsx"].map((fmt) => (
            <button
              key={fmt}
              onClick={() => handleExport(fmt)}
              disabled={exporting}
              aria-label={`Export as ${fmt.toUpperCase()}`}
              title={`Export as ${fmt.toUpperCase()}`}
              className="text-xs px-2.5 py-1 text-text-secondary hover:text-text-primary hover:bg-surface-2 rounded transition-colors disabled:opacity-50 min-h-[28px]"
            >
              {fmt.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
      <div className="overflow-x-auto max-h-96 data-table-scroll">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border-subtle">
              {columns.map((col) => (
                <th
                  key={col}
                  className="px-4 py-2 text-left text-text-secondary font-medium whitespace-nowrap"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length || 1} className="px-4 py-8 text-center text-text-tertiary text-xs">
                  No data returned
                </td>
              </tr>
            ) : rows.map((row, i) => (
              <tr key={`${i}-${columns.length > 0 ? String(row[columns[0]] ?? "") : i}`} className="border-b border-border-subtle/50 hover:bg-surface-2/30">
                {columns.map((col) => (
                  <td key={col} className="px-4 py-2 text-text-primary whitespace-nowrap">
                    {row[col] == null ? (
                      <span className="text-text-muted">NULL</span>
                    ) : (
                      String(row[col])
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {isCapped && (
        <div className="px-4 py-2 border-t border-border-subtle/50 text-center">
          <button
            onClick={() => setShowAll(true)}
            className="text-[11px] text-accent hover:text-accent-hover transition-colors"
          >
            Showing {MAX_RENDERED_ROWS} of {allRows.length} rows — click to show all
          </button>
        </div>
      )}
    </div>
  );
}
