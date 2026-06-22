"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ErrorLogItem } from "@/lib/api/types";
import { Icon } from "@/components/ui/Icon";

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

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.logs.errors(projectId, {
        source: source || undefined,
        status: status || undefined,
        page_size: 100,
      });
      setItems(res.items);
    } catch {
      setItems([]);
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
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-border-subtle">
        <select
          aria-label="Filter by source"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          className="text-xs bg-surface-1 border border-border-subtle rounded px-2 py-1 text-text-secondary"
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
          className="text-xs bg-surface-1 border border-border-subtle rounded px-2 py-1 text-text-secondary"
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
        ) : items.length === 0 ? (
          <div className="p-6 text-center text-xs text-text-tertiary">No errors recorded</div>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-[10px] text-text-tertiary uppercase tracking-wider">
              <tr className="border-b border-border-subtle">
                <th className="text-left px-4 py-2">Message</th>
                <th className="text-left px-2 py-2">Source</th>
                <th className="text-left px-2 py-2">Kind</th>
                <th className="text-right px-2 py-2">Count</th>
                <th className="text-left px-2 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((e) => (
                <tr key={e.id} className="border-b border-border-subtle hover:bg-surface-1/50">
                  <td className="px-4 py-2 max-w-md truncate text-text-primary" title={e.message}>
                    {e.message}
                  </td>
                  <td className="px-2 py-2 text-text-tertiary">{e.source}</td>
                  <td className="px-2 py-2 text-text-tertiary">{e.kind}</td>
                  <td className="px-2 py-2 text-right tabular-nums text-text-secondary">
                    {e.occurrences}
                  </td>
                  <td className="px-2 py-2">
                    <button
                      onClick={() => void cycleStatus(e)}
                      aria-label={`Cycle status for ${e.id}`}
                      className={`text-[10px] px-2 py-0.5 rounded border border-border-subtle ${
                        e.status === "resolved"
                          ? "text-success"
                          : e.status === "acknowledged"
                            ? "text-warning"
                            : "text-error"
                      }`}
                    >
                      {e.status}
                    </button>
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
