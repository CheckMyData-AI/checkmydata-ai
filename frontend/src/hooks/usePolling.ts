import { useEffect, useRef } from "react";

/**
 * Unified polling hook (T30). Wraps setInterval with safe lifecycle hygiene:
 * - Automatic cleanup on unmount or when deps change
 * - Optional max duration before polling is stopped
 * - Pauses when the tab is hidden (Page Visibility API) to avoid burning
 *   resources on background tabs
 * - Calls the latest callback even when the ref changes between renders
 *
 * Usage:
 *   usePolling(tick, 3_000, [activeId]);
 *   usePolling(tick, 3_000, [activeId], { maxDurationMs: 15 * 60_000 });
 */
export interface PollingOptions {
  /** Stop polling after this many ms even if the component is still mounted. */
  maxDurationMs?: number;
  /** If true (default) poll only while document is visible. */
  pauseWhenHidden?: boolean;
  /** Fire the callback immediately when polling starts. */
  leading?: boolean;
  /** Polling is active only when this is truthy. */
  enabled?: boolean;
}

export function usePolling(
  callback: () => void | Promise<void>,
  intervalMs: number,
  deps: ReadonlyArray<unknown> = [],
  options: PollingOptions = {},
): void {
  const {
    maxDurationMs,
    pauseWhenHidden = true,
    leading = false,
    enabled = true,
  } = options;

  const cbRef = useRef(callback);
  cbRef.current = callback;

  useEffect(() => {
    if (!enabled) return;

    let intervalId: ReturnType<typeof setInterval> | null = null;
    let stopTimeoutId: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    const fire = () => {
      if (stopped) return;
      try {
        const result = cbRef.current();
        if (result && typeof (result as Promise<void>).then === "function") {
          (result as Promise<void>).catch(() => {
            /* swallow errors; callers must surface their own */
          });
        }
      } catch {
        /* swallow errors; callers must surface their own */
      }
    };

    const start = () => {
      if (intervalId !== null) return;
      intervalId = setInterval(fire, intervalMs);
    };
    const pause = () => {
      if (intervalId !== null) {
        clearInterval(intervalId);
        intervalId = null;
      }
    };

    if (leading) fire();
    start();

    let visibilityHandler: (() => void) | null = null;
    if (pauseWhenHidden && typeof document !== "undefined") {
      visibilityHandler = () => {
        if (document.hidden) pause();
        else if (!stopped) start();
      };
      document.addEventListener("visibilitychange", visibilityHandler);
    }

    if (maxDurationMs && maxDurationMs > 0) {
      stopTimeoutId = setTimeout(() => {
        stopped = true;
        pause();
      }, maxDurationMs);
    }

    return () => {
      stopped = true;
      pause();
      if (stopTimeoutId !== null) clearTimeout(stopTimeoutId);
      if (visibilityHandler && typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", visibilityHandler);
      }
    };
    // Intentionally spread deps — callers pass them explicitly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, enabled, leading, pauseWhenHidden, maxDurationMs, ...deps]);
}
