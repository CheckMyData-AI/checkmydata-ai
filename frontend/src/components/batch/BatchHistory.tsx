"use client";

import { useCallback, useEffect, useState } from "react";

import { Icon } from "@/components/ui/Icon";
import { ListError } from "@/components/ui/ListError";
import { api } from "@/lib/api";
import type { BatchQueryDTO } from "@/lib/api/types";
import { toast } from "@/stores/toast-store";

/**
 * Past batch runs, which the interface has never shown.
 *
 * `GET /api/batch?project_id=` and `DELETE /api/batch/{id}` have had typed clients
 * (`workspace.ts:308-310`) and no component caller: a user opened the runner,
 * executed, read the results in the modal, and closing it was final. The rows stayed
 * in the database and left the product.
 */
export function BatchHistory({
  projectId,
  onOpen,
}: {
  projectId: string;
  onOpen?: (batch: BatchQueryDTO) => void;
}) {
  const [runs, setRuns] = useState<BatchQueryDTO[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setRuns(await api.batch.list(projectId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load past runs.");
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const remove = async (id: string) => {
    try {
      await api.batch.delete(id);
      setRuns((prev) => prev?.filter((r) => r.id !== id) ?? null);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not delete that run.", "error");
    }
  };

  if (error) return <ListError message={error} onRetry={load} />;
  if (runs === null) {
    return <p className="text-meta text-text-muted px-1 py-2">Loading past runs…</p>;
  }
  if (runs.length === 0) {
    return (
      <p className="text-meta text-text-muted px-1 py-2">
        No batch runs yet. Results from a run will be listed here.
      </p>
    );
  }

  return (
    <ul className="space-y-1" aria-label="Past batch runs">
      {runs.map((run) => {
        let count = 0;
        try {
          count = JSON.parse(run.queries_json || "[]").length;
        } catch {
          count = 0;
        }
        return (
          <li
            key={run.id}
            className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-surface-2/60 transition-colors"
          >
            <button
              type="button"
              onClick={() => onOpen?.(run)}
              className="flex-1 text-left min-w-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring rounded"
            >
              <span className="block text-sm text-text-primary truncate">{run.title}</span>
              <span className="block text-meta text-text-muted">
                {count} {count === 1 ? "query" : "queries"} · {run.status}
                {run.completed_at ? ` · ${new Date(run.completed_at).toLocaleString()}` : ""}
              </span>
            </button>
            <button
              type="button"
              onClick={() => remove(run.id)}
              aria-label={`Delete ${run.title}`}
              title="Delete this run"
              className="shrink-0 text-text-muted hover:text-danger transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring rounded p-1"
            >
              <Icon name="trash" size={14} />
            </button>
          </li>
        );
      })}
    </ul>
  );
}
