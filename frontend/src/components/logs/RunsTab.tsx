"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { RunHistoryItem } from "@/lib/api/types";
import { Icon } from "@/components/ui/Icon";
import { ListError } from "@/components/ui/ListError";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/shadcn/table";
import { StatusDot } from "@/components/ui/StatusDot";

const KINDS = ["", "index_repo", "db_index", "code_db_sync", "daily_sync"];

export function RunsTab({ projectId }: { projectId: string }) {
  const [rows, setRows] = useState<RunHistoryItem[]>([]);
  const [kind, setKind] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.logs.runs(projectId, { kind: kind || undefined, limit: 100 });
      setRows(data);
    } catch (e) {
      setRows([]);
      setError(e instanceof Error ? e.message : "Failed to load runs");
    } finally {
      setLoading(false);
    }
  }, [projectId, kind]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-border-subtle">
        <select
          aria-label="Filter by kind"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          className="text-xs bg-surface-1 border border-border-subtle rounded px-2 py-1 text-text-secondary"
        >
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {k || "All kinds"}
            </option>
          ))}
        </select>
        <button
          onClick={() => void load()}
          aria-label="Refresh runs"
          className="ml-auto p-1 rounded text-text-muted hover:bg-surface-2"
        >
          <Icon name="refresh-cw" size={13} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && rows.length === 0 ? (
          <div className="p-6 text-center text-xs text-text-tertiary animate-pulse">Loading runs…</div>
        ) : error ? (
          <ListError message={error} onRetry={() => void load()} />
        ) : rows.length === 0 ? (
          <div className="p-6 text-center text-xs text-text-tertiary">No runs recorded</div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-4">Kind</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Trigger</TableHead>
                <TableHead className="text-right">Finished</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.id}>
                  <TableCell className="pl-4 text-text-primary">{r.kind}</TableCell>
                  <TableCell>
                    {/* Status is never by colour alone: the dot carries the hue
                        and the word stays in --ink, because --ok and --danger
                        both sit under AA on the light field. */}
                    <span className="inline-flex items-center gap-2">
                      <StatusDot
                        status={
                          r.status === "failed"
                            ? "error"
                            : r.status === "completed"
                              ? "success"
                              : "idle"
                        }
                        title={r.status}
                      />
                      <span className="text-text-primary">{r.status}</span>
                    </span>
                  </TableCell>
                  <TableCell className="text-text-tertiary">{r.trigger}</TableCell>
                  <TableCell className="text-right font-mono text-meta text-text-tertiary tabular-nums">
                    {r.finished_at ? new Date(r.finished_at).toLocaleString() : "—"}
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
