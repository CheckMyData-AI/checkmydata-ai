"use client";

import { useEffect, useState } from "react";
import { api, type SyncStatus } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";

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

export function SyncStatusIndicator() {
  const { activeConnection } = useAppStore();
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);

  useEffect(() => {
    if (!activeConnection) {
      setSyncStatus(null);
      return;
    }
    api.connections.syncStatus(activeConnection.id).then(setSyncStatus).catch(() => {});
  }, [activeConnection]);

  if (!activeConnection || !syncStatus) return null;

  const { is_synced, sync_status, synced_tables, total_tables, synced_at } = syncStatus;

  if (!is_synced && sync_status !== "stale" && sync_status !== "running") return null;

  const dotColor = sync_status === "running"
    ? "bg-amber-400 animate-pulse"
    : sync_status === "stale"
      ? "bg-amber-500"
      : is_synced
        ? "bg-green-400"
        : "bg-zinc-600";

  const label = sync_status === "running"
    ? "Syncing..."
    : sync_status === "stale"
      ? "Sync stale"
      : `${synced_tables ?? 0}/${total_tables ?? 0} tables matched`;

  const ageStr = synced_at ? timeAgo(synced_at) : null;

  return (
    <div className="mt-1 px-2 flex items-center gap-1.5 text-[10px] text-zinc-500">
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotColor}`} />
      <span>SYNC</span>
      <span className="text-zinc-600">·</span>
      <span className="truncate">{label}</span>
      {ageStr && (
        <>
          <span className="text-zinc-600">·</span>
          <span>{ageStr}</span>
        </>
      )}
    </div>
  );
}
