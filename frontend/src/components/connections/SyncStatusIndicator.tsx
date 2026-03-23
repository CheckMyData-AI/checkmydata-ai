"use client";

import { useEffect, useRef, useState } from "react";
import { api, type SyncStatus } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { useTaskStore } from "@/stores/task-store";
import { toast } from "@/stores/toast-store";

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

const REFRESH_PIPELINES = new Set(["code_db_sync", "db_index"]);

export function SyncStatusIndicator() {
  const activeConnection = useAppStore((s) => s.activeConnection);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const tasks = useTaskStore((s) => s.tasks);
  const prevFinishedRef = useRef<Set<string>>(new Set());
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!activeConnection) {
      setSyncStatus(null);
      return;
    }
    let cancelled = false;
    const connId = activeConnection.id;
    api.connections
      .syncStatus(connId)
      .then((s) => { if (!cancelled) setSyncStatus(s); })
      .catch(() => { if (!cancelled) toast("Could not load sync status", "error"); });
    return () => { cancelled = true; };
  }, [activeConnection]);

  useEffect(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }

    if (!activeConnection || syncStatus?.sync_status !== "running") return;

    const connId = activeConnection.id;
    let cancelled = false;
    let pollFailures = 0;
    pollRef.current = setInterval(() => {
      if (cancelled) return;
      api.connections
        .syncStatus(connId)
        .then((s) => { if (!cancelled) { setSyncStatus(s); pollFailures = 0; } })
        .catch(() => { if (!cancelled && ++pollFailures >= 3) toast("Sync status polling failing", "error"); });
    }, 5000);

    return () => {
      cancelled = true;
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [activeConnection, syncStatus?.sync_status]);

  const prevRunningRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!activeConnection) return;

    const finished = new Set<string>();
    const running = new Set<string>();
    for (const t of Object.values(tasks)) {
      if (
        REFRESH_PIPELINES.has(t.pipeline) &&
        t.extra.connection_id === activeConnection.id
      ) {
        if (t.status === "running") {
          running.add(t.workflowId);
        } else {
          finished.add(t.workflowId);
        }
      }
    }

    const newFinished = [...finished].some((id) => !prevFinishedRef.current.has(id));
    const newRunning = [...running].some((id) => !prevRunningRef.current.has(id));
    prevFinishedRef.current = finished;
    prevRunningRef.current = running;

    if (newFinished || newRunning) {
      api.connections.syncStatus(activeConnection.id).then(setSyncStatus).catch(() => {
        toast("Could not refresh sync status", "error");
      });
    }
  }, [tasks, activeConnection]);

  if (!activeConnection || !syncStatus) return null;

  const { is_synced, sync_status, synced_tables, total_tables, synced_at } = syncStatus;

  if (!is_synced && sync_status !== "stale" && sync_status !== "running") return null;

  const dotColor = sync_status === "running"
    ? "bg-warning animate-pulse-dot"
    : sync_status === "stale"
      ? "bg-warning"
      : is_synced
        ? "bg-success"
        : "bg-surface-3";

  const label = sync_status === "running"
    ? "Syncing..."
    : sync_status === "stale"
      ? "Sync stale"
      : `${synced_tables ?? 0}/${total_tables ?? 0} tables matched`;

  const ageStr = synced_at ? timeAgo(synced_at) : null;

  return (
    <div className="mt-1 px-2 flex items-center gap-1.5 text-[10px] text-text-muted">
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotColor}`} />
      <span>SYNC</span>
      <span className="text-text-tertiary">&middot;</span>
      <span className="truncate">{label}</span>
      {ageStr && (
        <>
          <span className="text-text-tertiary">&middot;</span>
          <span>{ageStr}</span>
        </>
      )}
    </div>
  );
}
