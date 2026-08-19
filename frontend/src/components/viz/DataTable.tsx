"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "@/stores/toast-store";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { isNull, numericColumns } from "./table-columns";

interface DataTableProps {
  data: Record<string, unknown>;
}

const MAX_RENDERED_ROWS = 500;

/**
 * The result table, on the pack's measured geometry: 32px rows on the
 * `--panel-2` data plane, a 12px `--muted` header over a hairline, hairline row
 * dividers, numeric columns right-aligned in the data face with tabular
 * figures, and a monospace row number in the first column — the pack's motif,
 * and the first thing dropped when the card gets narrow.
 *
 * The table sits on `--panel-2` and never directly on the field, because the
 * row hover is one step from the page background in light mode and would be
 * invisible there.
 *
 * The per-row entrance cascade this used to carry is gone on purpose: a result
 * table renders on every query, which puts it in the row of the motion
 * doctrine's frequency table where animation is cut to the floor. Waiting
 * 28ms × 16 to read a number you already asked for is a cost, not a delight.
 */
export function DataTable({ data }: DataTableProps) {
  // Memoised because the `|| []` fallback allocates a new array on every render,
  // which would make the numeric-column scan below re-run for every keystroke
  // elsewhere on the page.
  const columns = useMemo(() => (data.columns as string[]) || [], [data.columns]);
  const allRows = useMemo(() => (data.rows as Record<string, unknown>[]) || [], [data.rows]);
  const totalRows = (data.total_rows as number) || allRows.length;
  const executionTime = data.execution_time_ms as number | undefined;
  const [exporting, setExporting] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const isCapped = allRows.length > MAX_RENDERED_ROWS && !showAll;
  const rows = isCapped ? allRows.slice(0, MAX_RENDERED_ROWS) : allRows;

  const numeric = useMemo(() => numericColumns(rows, columns), [rows, columns]);

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
    <div className="@container overflow-hidden rounded-card border border-border bg-panel-2">
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <span className="font-mono text-meta text-text-tertiary tabular-nums">
          {totalRows} row{totalRows !== 1 ? "s" : ""}
          {executionTime != null && ` · ${executionTime.toFixed(0)}ms`}
        </span>
        <div className="flex gap-1">
          {["csv", "json", "xlsx"].map((fmt) => (
            <Button
              key={fmt}
              variant="ghost"
              size="sm"
              onClick={() => handleExport(fmt)}
              disabled={exporting}
              aria-label={`Export as ${fmt.toUpperCase()}`}
              title={`Export as ${fmt.toUpperCase()}`}
              className="font-mono text-kicker tracking-kicker uppercase"
            >
              {fmt.toUpperCase()}
            </Button>
          ))}
        </div>
      </div>

      <div className="data-table-scroll max-h-96 overflow-x-auto">
        <table className="w-full text-body">
          <thead className="sticky top-0 bg-panel-2">
            <tr className="border-b border-border">
              <th
                scope="col"
                aria-label="Row number"
                className="w-8 border-b border-border @max-[32rem]:hidden"
              />
              {columns.map((col) => (
                <th
                  key={col}
                  scope="col"
                  className={cn(
                    "h-8 whitespace-nowrap px-2 text-meta font-normal text-text-tertiary",
                    numeric.has(col) ? "text-right" : "text-left",
                  )}
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td
                  colSpan={(columns.length || 1) + 1}
                  className="px-4 py-8 text-center text-meta text-text-tertiary"
                >
                  No data returned
                </td>
              </tr>
            ) : (
              rows.map((row, i) => (
                <tr
                  key={`${i}-${columns.length > 0 ? String(row[columns[0]] ?? "") : i}`}
                  className="border-b border-border last:border-0 hover:bg-row-hover"
                >
                  <td className="w-8 px-2 text-right font-mono text-meta text-text-tertiary tabular-nums @max-[32rem]:hidden">
                    {i + 1}
                  </td>
                  {columns.map((col) => (
                    <td
                      key={col}
                      className={cn(
                        "h-8 whitespace-nowrap px-2 text-text-primary",
                        numeric.has(col)
                          ? "text-right font-mono tabular-nums"
                          : "text-left",
                      )}
                    >
                      {isNull(row[col]) ? (
                        <span className="font-mono text-text-muted">NULL</span>
                      ) : (
                        String(row[col])
                      )}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {isCapped && (
        <div className="border-t border-border px-4 py-2 text-center">
          <button
            onClick={() => setShowAll(true)}
            className="font-mono text-kicker tracking-kicker uppercase text-accent transition-colors hover:text-ink"
          >
            Showing {MAX_RENDERED_ROWS} of {allRows.length} rows — click to show all
          </button>
        </div>
      )}
    </div>
  );
}
