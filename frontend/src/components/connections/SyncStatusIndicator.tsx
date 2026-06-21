"use client";

import { useEffect, useRef, useState } from "react";
import { api, type SyncStatus } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { useBackgroundTasks } from "@/stores/background-tasks-store";
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
  const activeProject = useAppStore((s) => s.activeProject);
  const activeConnection = useAppStore((s) => s.activeConnection);
  const pipelineStatus = useAppStore((s) =>
    activeProject ? s.pipelineStatusByProject[activeProject.id] : undefined,
  );
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const tasks = useBackgroundTasks((s) => s.tasks);
  const prevFinishedRef = useRef<Set<string>>(new Set());

  const connPipeline = pipelineStatus?.connections.find(
    (c) => c.connection_id === activeConnection?.id,
  );
  const pipelineSyncStatus = connPipeline?.code_db_sync.sync_status;

  // Single source of truth for the "is syncing" running state: the unified
  // background-tasks store's per-connection sync task (fed by SSE + the central
  // pipeline-status poll in useKnowledgePipelineStatus). This component no
  // longer runs its own /sync/status polling loop — it only fetches once to
  // reconcile the synced_tables/total_tables/synced_at detail fields.
  const syncTask = activeConnection ? tasks[`sync:${activeConnection.id}`] : undefined;
  const storeSyncRunning = syncTask?.status === "running";

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

  if (!activeConnection) return null;

  const effectiveSyncStatus =
    syncStatus?.sync_status ?? pipelineSyncStatus ?? "idle";
  const isSyncing = storeSyncRunning;
  const isSynced = syncStatus?.is_synced ?? false;
  const syncedTables = syncStatus?.synced_tables ?? connPipeline?.code_db_sync.synced_tables;
  const totalTables = syncStatus?.total_tables ?? connPipeline?.code_db_sync.total_tables;
  const syncedAt = syncStatus?.synced_at ?? connPipeline?.code_db_sync.synced_at ?? undefined;

  const dotColor = isSyncing
    ? "bg-warning animate-pulse-dot"
    : effectiveSyncStatus === "stale"
      ? "bg-warning"
      : isSynced
        ? "bg-success"
        : "bg-surface-3";

  const label = isSyncing
    ? "Syncing..."
    : effectiveSyncStatus === "stale"
      ? "Sync stale"
      : isSynced
        ? `${syncedTables ?? 0}/${totalTables ?? 0} tables matched`
        : "Not synced yet";

  const ageStr = syncedAt ? timeAgo(syncedAt) : null;

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
