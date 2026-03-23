"use client";

import { useEffect, useRef } from "react";
import { broadcastEvent, subscribeToAllEvents, type WorkflowEvent } from "@/lib/sse";
import { api } from "@/lib/api";
import { useLogStore } from "@/stores/log-store";
import { useTaskStore } from "@/stores/task-store";

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
  const activeRef = useRef(false);

  useEffect(() => {
    if (!enabled) {
      unsubRef.current?.();
      unsubRef.current = null;
      activeRef.current = false;
      useLogStore.getState().setConnected(false);
      return;
    }

    activeRef.current = true;

    function seedActiveTasks() {
      api.tasks.getActive().then(
        (tasks) => { if (activeRef.current) useTaskStore.getState().seedFromApi(tasks); },
        () => {},
      );
    }

    function scheduleReconnect() {
      useLogStore.getState().setConnected(false);
      const delay = Math.min(
        RECONNECT_BASE_MS * 2 ** attemptRef.current,
        RECONNECT_MAX_MS,
      );
      attemptRef.current++;
      timerRef.current = setTimeout(connect, delay);
    }

    function connect() {
      unsubRef.current?.();

      seedActiveTasks();

      const unsub = subscribeToAllEvents(
        (event: WorkflowEvent) => {
          attemptRef.current = 0;
          useLogStore.getState().setConnected(true);
          useLogStore.getState().addEntry(toLogEntry(event));
          useTaskStore.getState().processEvent(event);
          broadcastEvent(event);
        },
        () => scheduleReconnect(),
        () => scheduleReconnect(),
      );

      unsubRef.current = unsub;
      useLogStore.getState().setConnected(true);
    }

    connect();

    return () => {
      activeRef.current = false;
      unsubRef.current?.();
      unsubRef.current = null;
      if (timerRef.current) clearTimeout(timerRef.current);
      useLogStore.getState().setConnected(false);
    };
  }, [enabled]);
}
