"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { RunHistoryItem } from "@/lib/api/types";
import { Icon } from "@/components/ui/Icon";

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
          <div className="p-6 text-center text-xs text-error flex flex-col items-center gap-2">
            <span>{error}</span>
            <button onClick={() => void load()} className="underline hover:no-underline">
              Retry
            </button>
          </div>
        ) : rows.length === 0 ? (
          <div className="p-6 text-center text-xs text-text-tertiary">No runs recorded</div>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-[10px] text-text-tertiary uppercase tracking-wider">
              <tr className="border-b border-border-subtle">
                <th className="text-left px-4 py-2">Kind</th>
                <th className="text-left px-2 py-2">Status</th>
                <th className="text-left px-2 py-2">Trigger</th>
                <th className="text-left px-2 py-2">Finished</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-border-subtle hover:bg-surface-1/50">
                  <td className="px-4 py-2 text-text-primary">{r.kind}</td>
                  <td className="px-2 py-2">
                    <span
                      className={
                        r.status === "failed"
                          ? "text-error"
                          : r.status === "completed"
                            ? "text-success"
                            : "text-text-secondary"
                      }
                    >
                      {r.status}
                    </span>
                  </td>
                  <td className="px-2 py-2 text-text-tertiary">{r.trigger}</td>
                  <td className="px-2 py-2 text-text-muted tabular-nums">
                    {r.finished_at ? new Date(r.finished_at).toLocaleString() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
