"use client";

import { useEffect, useRef } from "react";
import { subscribeToAllEvents, type WorkflowEvent } from "@/lib/sse";
import { useLogStore } from "@/stores/log-store";

const RECONNECT_BASE_MS = 2000;
const RECONNECT_MAX_MS = 30000;

function toLogEntry(ev: WorkflowEvent) {
  return {
    timestamp: ev.timestamp,
    pipeline: ev.pipeline || "system",
    workflowId: ev.workflow_id.slice(0, 8),
    step: ev.step,
    status: ev.status,
    detail: ev.detail,
    elapsedMs: ev.elapsed_ms,
  };
}

export function useGlobalEvents(enabled: boolean) {
  const attemptRef = useRef(0);
  const unsubRef = useRef<(() => void) | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!enabled) {
      unsubRef.current?.();
      unsubRef.current = null;
      useLogStore.getState().setConnected(false);
      return;
    }

    function connect() {
      unsubRef.current?.();

      const unsub = subscribeToAllEvents(
        (event: WorkflowEvent) => {
          attemptRef.current = 0;
          useLogStore.getState().setConnected(true);
          useLogStore.getState().addEntry(toLogEntry(event));
        },
        () => {
          useLogStore.getState().setConnected(false);
          const delay = Math.min(
            RECONNECT_BASE_MS * 2 ** attemptRef.current,
            RECONNECT_MAX_MS,
          );
          attemptRef.current++;
          timerRef.current = setTimeout(connect, delay);
        },
      );

      unsubRef.current = unsub;
      useLogStore.getState().setConnected(true);
    }

    connect();

    return () => {
      unsubRef.current?.();
      unsubRef.current = null;
      if (timerRef.current) clearTimeout(timerRef.current);
      useLogStore.getState().setConnected(false);
    };
  }, [enabled]);
}
