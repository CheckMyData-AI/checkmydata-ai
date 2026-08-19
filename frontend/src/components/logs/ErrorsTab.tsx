"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ErrorLogItem } from "@/lib/api/types";
import { Icon } from "@/components/ui/Icon";
import { ListError } from "@/components/ui/ListError";
import { toast } from "@/stores/toast-store";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/shadcn/table";
import { StatusDot } from "@/components/ui/StatusDot";
import { cn } from "@/lib/utils";
import { selectBaseCls } from "@/components/ui/Input";

const SOURCES = ["", "run", "query", "span", "system"];
const STATUSES = ["", "open", "acknowledged", "resolved"];
const NEXT_STATUS: Record<string, string> = {
  open: "acknowledged",
  acknowledged: "resolved",
  resolved: "open",
};

export function ErrorsTab({ projectId }: { projectId: string }) {
  const [items, setItems] = useState<ErrorLogItem[]>([]);
  const [source, setSource] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.logs.errors(projectId, {
        source: source || undefined,
        status: status || undefined,
        page_size: 100,
      });
      setItems(res.items);
    } catch (e) {
      setItems([]);
      setError(e instanceof Error ? e.message : "Failed to load errors");
    } finally {
      setLoading(false);
    }
  }, [projectId, source, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const cycleStatus = async (e: ErrorLogItem) => {
    const next = NEXT_STATUS[e.status] || "open";
    try {
      await api.logs.updateError(projectId, e.id, next);
      setItems((prev) => prev.map((x) => (x.id === e.id ? { ...x, status: next as ErrorLogItem["status"] } : x)));
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to update error status", "error");
    }
  };

  return (
    <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-border-subtle">
        <select
          aria-label="Filter by source"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          className={selectBaseCls}
        >
          {SOURCES.map((s) => (
            <option key={s} value={s}>
              {s || "All sources"}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter by status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className={selectBaseCls}
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s || "All statuses"}
            </option>
          ))}
        </select>
        <button
          onClick={() => void load()}
          aria-label="Refresh errors"
          className="ml-auto p-1 rounded text-text-muted hover:bg-surface-2"
        >
          <Icon name="refresh-cw" size={13} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && items.length === 0 ? (
          <div className="p-6 text-center text-xs text-text-tertiary animate-pulse">Loading errors…</div>
        ) : error ? (
          <ListError message={error} onRetry={() => void load()} />
        ) : items.length === 0 ? (
          <div className="p-6 text-center text-xs text-text-tertiary">No errors recorded</div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-4">Message</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead className="text-right">Count</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="max-w-md truncate pl-4 text-text-primary" title={e.message}>
                    {e.message}
                  </TableCell>
                  <TableCell className="text-text-tertiary">{e.source}</TableCell>
                  <TableCell className="text-text-tertiary">{e.kind}</TableCell>
                  <TableCell className="text-right font-mono text-text-primary tabular-nums">
                    {e.occurrences}
                  </TableCell>
                  <TableCell>
                    {/* The status is a control here — it cycles. Its hue rides
                        the border and the dot; the word stays in --ink, because
                        every one of these three sits under AA on the field. */}
                    <button
                      onClick={() => void cycleStatus(e)}
                      aria-label={`Cycle status for ${e.id}`}
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-control border px-2 py-0.5",
                        "font-mono text-kicker uppercase tracking-kicker text-ink",
                        "transition-colors duration-(--dur) ease-(--ease) hover:bg-inset",
                        e.status === "resolved"
                          ? "border-ok/40"
                          : e.status === "acknowledged"
                            ? "border-warn/40"
                            : "border-danger/40",
                      )}
                    >
                      <StatusDot
                        status={
                          e.status === "resolved"
                            ? "success"
                            : e.status === "acknowledged"
                              ? "warning"
                              : "error"
                        }
                        title={e.status}
                      />
                      {e.status}
                    </button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}
