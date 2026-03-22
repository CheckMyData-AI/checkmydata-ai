"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { toast } from "@/stores/toast-store";

interface DataTableProps {
  data: Record<string, unknown>;
}

export function DataTable({ data }: DataTableProps) {
  const columns = (data.columns as string[]) || [];
  const rows = (data.rows as Record<string, unknown>[]) || [];
  const totalRows = (data.total_rows as number) || rows.length;
  const executionTime = data.execution_time_ms as number | undefined;
  const [exporting, setExporting] = useState(false);

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
    <div className="bg-zinc-900 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-zinc-800">
        <span className="text-xs text-zinc-400">
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
              className="text-xs px-2.5 py-1 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 rounded transition-colors disabled:opacity-50 min-h-[28px]"
            >
              {fmt.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
      <div className="overflow-x-auto max-h-96">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-zinc-800">
              {columns.map((col) => (
                <th
                  key={col}
                  className="px-4 py-2 text-left text-zinc-400 font-medium whitespace-nowrap"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length || 1} className="px-4 py-8 text-center text-zinc-500 text-xs">
                  No data returned
                </td>
              </tr>
            ) : rows.map((row, i) => (
              <tr key={`${i}-${columns.length > 0 ? String(row[columns[0]] ?? "") : i}`} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                {columns.map((col) => (
                  <td key={col} className="px-4 py-2 text-zinc-300 whitespace-nowrap">
                    {row[col] == null ? (
                      <span className="text-zinc-600">NULL</span>
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
    </div>
  );
}
