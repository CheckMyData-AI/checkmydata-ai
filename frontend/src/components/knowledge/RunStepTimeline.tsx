"use client";

import { useCallback, useEffect, useState } from "react";

import { Icon } from "@/components/ui/Icon";
import { api } from "@/lib/api";
import type { RunEvent } from "@/lib/api/runs";

/**
 * What a run actually did, step by step — the half a failure message leaves out.
 *
 * `GET /api/runs/{id}/events` returns each step with its status, detail,
 * `elapsed_ms` and `progress_pct`, and had a typed client (`runs.ts:24-25`) with no
 * caller. So when a repository index died at `graph_build`, the interface could say
 * *"stale run reaped"* and nothing about which step, how far in, or how long it had
 * been working — the three things that decide what to do next.
 */
function toneOf(level: string, status: string): string {
  if (status === "failed" || level === "error") return "text-error";
  if (level === "warning") return "text-warning";
  if (status === "completed") return "text-success";
  return "text-text-muted";
}

export function RunStepTimeline({ runId }: { runId: string }) {
  const [events, setEvents] = useState<RunEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setEvents(await api.runs.events(runId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the step log.");
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return (
      <div className="text-kicker text-text-muted px-1 py-1 space-y-1">
        <p>{error}</p>
        <button type="button" onClick={load} className="text-accent hover:underline">
          Try again
        </button>
      </div>
    );
  }
  if (events === null) {
    return <p className="text-kicker text-text-muted px-1 py-1">Loading steps…</p>;
  }
  if (events.length === 0) {
    return (
      <p className="text-kicker text-text-muted px-1 py-1">
        This run recorded no steps — it ended before the first one started.
      </p>
    );
  }

  return (
    <ol className="space-y-0.5" aria-label="Run steps">
      {events.map((e, i) => (
        <li key={`${e.step}-${i}`} className="flex items-start gap-1.5 text-kicker">
          <span className={`shrink-0 mt-0.5 ${toneOf(e.level, e.status)}`}>
            <Icon
              name={
                e.status === "failed"
                  ? "alert-triangle"
                  : e.status === "completed"
                    ? "check"
                    : "chevron-right"
              }
              size={9}
            />
          </span>
          <span className="flex-1 min-w-0">
            <span className={`font-mono ${toneOf(e.level, e.status)}`}>{e.step}</span>
            {e.detail ? <span className="text-text-muted"> · {e.detail}</span> : null}
          </span>
          {e.elapsed_ms !== null && (
            <span className="shrink-0 text-text-tertiary tabular-nums">
              {e.elapsed_ms >= 1000
                ? `${(e.elapsed_ms / 1000).toFixed(1)}s`
                : `${e.elapsed_ms}ms`}
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}
