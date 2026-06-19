"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type PipelineStatusResponse } from "@/lib/api";
import { POLL_INTERVAL_MS } from "@/lib/polling";
import { useAppStore } from "@/stores/app-store";
import { useTaskStore } from "@/stores/task-store";

const IDLE_POLL_MS = 30_000;

export function useKnowledgePipelineStatus(projectId: string | null | undefined) {
  const [status, setStatus] = useState<PipelineStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const prevAnyRunningRef = useRef<boolean | null>(null);
  const mountedRef = useRef(true);

  const fetchStatus = useCallback(async () => {
    if (!projectId) {
      setStatus(null);
      return null;
    }
    try {
      const data = await api.projects.pipelineStatus(projectId);
      if (!mountedRef.current) return null;
      setError(false);
      setStatus(data);
      useAppStore.getState().setPipelineStatus(projectId, data);
      useTaskStore.getState().seedFromPipelineStatus(data);

      const wasRunning = prevAnyRunningRef.current;
      if (wasRunning === true && !data.any_running) {
        useAppStore.getState().clearReadinessCache(projectId);
      }
      prevAnyRunningRef.current = data.any_running;
      return data;
    } catch {
      if (mountedRef.current) setError(true);
      return null;
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!projectId) {
      setStatus(null);
      prevAnyRunningRef.current = null;
      return;
    }
    setLoading(true);
    prevAnyRunningRef.current = null;
    useAppStore.getState().setPipelineStatus(projectId, null);
    void fetchStatus();
  }, [projectId, fetchStatus]);

  useEffect(() => {
    if (!projectId) return;

    const intervalMs = status?.any_running ? POLL_INTERVAL_MS : IDLE_POLL_MS;
    const id = setInterval(() => {
      void fetchStatus();
    }, intervalMs);

    return () => clearInterval(id);
  }, [projectId, status?.any_running, fetchStatus]);

  useEffect(() => {
    if (!projectId) return;

    function onFocus() {
      void fetchStatus();
    }
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [projectId, fetchStatus]);

  return { status, loading, error, refresh: fetchStatus };
}
