"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ConnectionHealthState } from "@/lib/api";
import type {
  CollectionOutcome,
  CollectionReportStatus,
  CollectionStatus,
} from "@/lib/api/connections";
import { Tooltip } from "@/components/ui/Tooltip";
import { ListError } from "@/components/ui/ListError";
import { onEvent, type WorkflowEvent } from "@/lib/sse";
import { isAnalyticsSource } from "@/lib/connection-source";
import { toast } from "@/stores/toast-store";

type HealthStatus = "healthy" | "degraded" | "down" | "unknown";

const STATUS_DOT_CLASSES: Record<HealthStatus, string> = {
  healthy: "bg-success",
  degraded: "bg-warning",
  down: "bg-error",
  unknown: "bg-surface-3",
};

const MIN_POLL_INTERVAL_MS = 30_000;

function formatCheckTime(iso: string | null): string {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  return `${Math.floor(mins / 60)}h ago`;
}

interface ConnectionHealthProps {
  connectionId: string;
  /**
   * The connection's source kind. An analytics source has no live session to
   * probe — `/health` can only ever answer `unknown` for it — so the request is
   * skipped and this component renders nothing; the collection row underneath
   * carries the real state.
   */
  sourceType?: string | null;
  onStatusChange?: (status: HealthStatus) => void;
}

export function ConnectionHealth({
  connectionId,
  sourceType,
  onStatusChange,
}: ConnectionHealthProps) {
  const collectedSource = isAnalyticsSource(sourceType);
  const [health, setHealth] = useState<ConnectionHealthState | null>(null);
  const [loading, setLoading] = useState(true);
  const [reconnecting, setReconnecting] = useState(false);
  const mountedRef = useRef(true);
  const onStatusChangeRef = useRef(onStatusChange);
  const lastFetchRef = useRef(0);

  onStatusChangeRef.current = onStatusChange;

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const fetchHealth = useCallback(() => {
    if (collectedSource) return;
    const now = Date.now();
    if (now - lastFetchRef.current < MIN_POLL_INTERVAL_MS) return;
    lastFetchRef.current = now;

    api.connections.health(connectionId)
      .then((h) => {
        if (mountedRef.current) {
          setHealth(h);
          setLoading(false);
          onStatusChangeRef.current?.(h.status as HealthStatus);
        }
      })
      .catch(() => {
        if (mountedRef.current) setLoading(false);
      });
  }, [connectionId, collectedSource]);

  useEffect(() => {
    lastFetchRef.current = 0;
    fetchHealth();
  }, [fetchHealth]);

  useEffect(() => {
    if (collectedSource) return;
    const unsub = onEvent((event: WorkflowEvent) => {
      if (
        event.step === "connection_health" &&
        event.extra?.connection_id === connectionId
      ) {
        setHealth((prev) => {
          const updated: ConnectionHealthState = {
            status: event.status as HealthStatus,
            latency_ms: (event.extra?.latency_ms as number) ?? 0,
            last_check: new Date().toISOString(),
            consecutive_failures: prev?.consecutive_failures ?? 0,
            last_error: (event.extra?.last_error as string) ?? null,
          };
          onStatusChangeRef.current?.(updated.status as HealthStatus);
          return updated;
        });
      }
    });
    return unsub;
  }, [connectionId, collectedSource]);

  const handleReconnect = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setReconnecting(true);
    try {
      const result = await api.connections.reconnect(connectionId);
      if (result.health) {
        setHealth(result.health);
        onStatusChangeRef.current?.(result.health.status as HealthStatus);
      }
    } catch (err) {
      toast(err instanceof Error ? err.message : "Reconnect failed", "error");
    } finally {
      if (mountedRef.current) setReconnecting(false);
    }
  };

  // A permanently grey "unknown" dot next to a source that is collecting fine
  // is a false signal, so a collected source shows no health dot at all.
  if (collectedSource) return null;

  if (loading) {
    return (
      <span className="inline-flex items-center" aria-label="Checking connection health">
        <span className="shrink-0 w-1.5 h-1.5 rounded-full bg-surface-3 animate-pulse" />
      </span>
    );
  }

  const status: HealthStatus = (health?.status as HealthStatus) ?? "unknown";
  const dotClass = STATUS_DOT_CLASSES[status];

  const tooltipLines = [
    `Status: ${status}`,
    health?.latency_ms ? `Latency: ${health.latency_ms}ms` : null,
    `Checked: ${formatCheckTime(health?.last_check ?? null)}`,
    health?.last_error ? `Error: ${health.last_error}` : null,
  ]
    .filter(Boolean)
    .join(" | ");

  return (
    <span className="inline-flex items-center gap-1">
      <Tooltip label={tooltipLines} position="bottom">
        <span
          className={`shrink-0 w-1.5 h-1.5 rounded-full inline-block ${dotClass} ${
            status === "degraded" ? "animate-pulse-dot" : ""
          }`}
          role="img"
          aria-label={`Connection health: ${status}`}
        />
      </Tooltip>
      {status === "down" && (
        <button
          type="button"
          onClick={handleReconnect}
          disabled={reconnecting}
          className="text-kicker px-1 py-px rounded-full bg-error-muted text-error hover:bg-error/20 outline-none focus-visible:ring-2 focus-visible:ring-accent leading-none disabled:opacity-50"
        >
          {reconnecting ? "..." : "RECONNECT"}
        </button>
      )}
    </span>
  );
}


/* ------------------------------------------------------------------ *
 * Analytics collection row (spec §6, SCN-115)
 * ------------------------------------------------------------------ */

const OUTCOME_BADGE_CLASSES: Record<CollectionOutcome, string> = {
  ok: "bg-success-muted text-success",
  partial: "bg-warning-muted text-warning",
  failed: "bg-error-muted text-error",
  never_collected: "bg-surface-3/50 text-text-muted",
};

const OUTCOME_LABELS: Record<CollectionOutcome, string> = {
  ok: "ok",
  partial: "partial",
  failed: "failed",
  never_collected: "not collected",
};

const OUTCOME_TOOLTIPS: Record<CollectionOutcome, string> = {
  ok: "Every period the backfill window expects has been collected.",
  partial: "Some periods landed, some are still owed — they are listed below.",
  failed: "Nothing was collected: every period failed.",
  never_collected: "This source has not been collected yet.",
};

/** Refresh cadence while a manually-requested collection is outstanding. */
const COLLECT_POLL_INTERVAL_MS = 5_000;
/** Stop chasing a queued job after this long; the schedule will catch up. */
const COLLECT_POLL_MAX_MS = 120_000;

function formatHour(hour: number | null | undefined): string | null {
  if (hour === null || hour === undefined) return null;
  if (!Number.isInteger(hour) || hour < 0 || hour > 23) return null;
  return `${String(hour).padStart(2, "0")}:00`;
}

/**
 * "Never collected" and "collected, and the answer was zero" are different
 * facts and must not render the same (SCN-115) — a gap invites a re-run, a
 * genuine zero does not.
 */
function coverageLabel(report: CollectionReportStatus): string {
  const through = report.latest_collected_period ?? report.latest_ok_period;
  if (!through) return "not collected yet";
  if (report.ok_periods === 0) return `collected through ${through} (no rows)`;
  return `collected through ${through}`;
}

interface CollectionStatusRowProps {
  connectionId: string;
  className?: string;
}

/**
 * The collection row shown under an analytics connection: outcome badge, last
 * run, pending periods, next scheduled hour and a manual "Collect now".
 *
 * The one rule this component exists to keep: `caveat` renders as a caveat and
 * `last_error` renders as an error, and never the other way round. A truncated
 * or sampled range is real data with a qualifier; painting it red would teach
 * the user to distrust numbers that are merely approximate — and painting a
 * genuine failure amber would hide a collection that produced nothing at all.
 */
export function CollectionStatusRow({
  connectionId,
  className = "",
}: CollectionStatusRowProps) {
  const [status, setStatus] = useState<CollectionStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [collecting, setCollecting] = useState(false);
  const [queued, setQueued] = useState(false);
  const mountedRef = useRef(true);
  const collectingRef = useRef(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // `last_run_at` as of the moment a manual collect was queued: the job is
  // done once the journal's newest timestamp moves past it.
  const queuedSinceRef = useRef<string | null | undefined>(undefined);

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, []);

  const fetchStatus = useCallback(
    async (opts?: { silent?: boolean }) => {
      const silent = opts?.silent === true;
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      try {
        const next = await api.connections.collectionStatus(connectionId);
        if (!mountedRef.current) return;
        setStatus(next);
        setError(null);
        if (
          queuedSinceRef.current !== undefined &&
          next.last_run_at !== queuedSinceRef.current
        ) {
          queuedSinceRef.current = undefined;
          setQueued(false);
          stopPoll();
        }
      } catch (err) {
        // A failed background refresh must not replace a row the user can read.
        if (!mountedRef.current || silent) return;
        setError(
          err instanceof Error ? err.message : "Failed to load collection status",
        );
      } finally {
        if (mountedRef.current && !silent) setLoading(false);
      }
    },
    [connectionId, stopPoll],
  );

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  const startCollectPoll = useCallback(() => {
    stopPoll();
    const startedAt = Date.now();
    pollRef.current = setInterval(() => {
      if (Date.now() - startedAt > COLLECT_POLL_MAX_MS) {
        stopPoll();
        if (mountedRef.current) setQueued(false);
        queuedSinceRef.current = undefined;
        return;
      }
      void fetchStatus({ silent: true });
    }, COLLECT_POLL_INTERVAL_MS);
  }, [fetchStatus, stopPoll]);

  const handleCollectNow = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (collectingRef.current) return;
    collectingRef.current = true;
    setCollecting(true);
    try {
      await api.connections.collectNow(connectionId);
      if (mountedRef.current) {
        queuedSinceRef.current = status?.last_run_at ?? null;
        setQueued(true);
        startCollectPoll();
      }
      toast("Collection queued", "success");
      await fetchStatus({ silent: true });
    } catch (err) {
      toast(err instanceof Error ? err.message : "Collect failed", "error");
    } finally {
      collectingRef.current = false;
      if (mountedRef.current) setCollecting(false);
    }
  };

  if (loading && !status && !error) {
    return (
      <div
        className={`mx-3 mb-1 px-2 py-1 text-kicker text-text-muted ${className}`}
        aria-label="Loading collection status"
      >
        Loading collection status…
      </div>
    );
  }

  if (error && !status) {
    return (
      <ListError
        message={error}
        onRetry={() => void fetchStatus()}
        className={`mx-3 mb-1 px-2 py-1 text-kicker text-error flex flex-col items-start gap-1 ${className}`}
      />
    );
  }

  if (!status) return null;

  const badge: CollectionOutcome = status.status ?? "never_collected";
  const nextHour = formatHour(status.next_scheduled_hour);

  return (
    <div
      className={`mx-3 mb-1 px-2 py-1.5 rounded bg-surface-1 border border-border-subtle compact-touch ${className}`}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-kicker text-text-tertiary font-medium">Collection</span>
        <Tooltip label={OUTCOME_TOOLTIPS[badge]} position="bottom">
          {/* The tooltip is where the badge's meaning is written down, and
              Tooltip opens on focus — so the badge is focusable, and carries
              the same sentence as its accessible name for anyone who never
              sees a popup. */}
          <span
            data-testid="collection-outcome"
            tabIndex={0}
            role="status"
            aria-label={`Collection status: ${OUTCOME_LABELS[badge]} — ${OUTCOME_TOOLTIPS[badge]}`}
            className={`text-kicker px-1.5 py-px rounded-full leading-none outline-none focus-visible:ring-2 focus-visible:ring-accent ${OUTCOME_BADGE_CLASSES[badge]}`}
          >
            {OUTCOME_LABELS[badge]}
          </span>
        </Tooltip>
        {queued && (
          <span className="text-kicker px-1.5 py-px rounded-full bg-warning-muted text-warning animate-pulse-dot leading-none">
            queued
          </span>
        )}
        <span className="text-kicker text-text-muted">
          Last run {formatCheckTime(status.last_run_at)}
        </span>
        {nextHour ? (
          <span className="text-kicker text-text-muted">
            Next run {nextHour}
            {status.timezone ? ` ${status.timezone}` : ""}
          </span>
        ) : (
          <span className="text-kicker px-1.5 py-px rounded-full bg-surface-3/50 text-text-muted leading-none">
            auto-collect off
          </span>
        )}
        <span className="ml-auto">
          <Tooltip
            label="Collect now — fill any gap without waiting for the scheduled hour"
            position="bottom"
          >
            <button
              type="button"
              aria-label="Collect now"
              onClick={(e) => void handleCollectNow(e)}
              disabled={collecting}
              className="text-kicker px-1.5 py-0.5 rounded-full bg-surface-3/50 text-text-secondary hover:text-text-primary hover:bg-surface-3 outline-none focus-visible:ring-2 focus-visible:ring-accent leading-none disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {collecting ? "…" : "Collect now"}
            </button>
          </Tooltip>
        </span>
      </div>

      {/* Only the report list. The payload's connection-level `caveat` /
          `last_error` are the newest report-level values promoted to the top,
          and every journal row that can set them also produces a report — so
          "no reports" and "something to say" cannot co-occur, and printing the
          summary alongside the list would just double up the same sentence. */}
      {status.reports.length > 0 && (
        <ul className="mt-1 space-y-0.5">
          {status.reports.map((report) => {
            const pending = report.pending_sample ?? [];
            return (
              <li key={report.report} className="text-kicker leading-relaxed">
                <span className="text-text-tertiary font-mono">{report.report}</span>{" "}
                <span className="text-text-muted">{coverageLabel(report)}</span>
                {report.pending_periods > 0 && (
                  <span className="text-warning">
                    {" "}
                    · {report.pending_periods} pending
                    {pending.length > 0 ? `: ${pending.join(", ")}` : ""}
                  </span>
                )}
                {report.caveat && (
                  <span data-testid="collection-caveat" className="block text-warning">
                    Caveat: {report.caveat}
                  </span>
                )}
                {report.last_error && (
                  <span
                    data-testid="collection-error"
                    role="alert"
                    className="block text-error"
                  >
                    {report.last_error}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
