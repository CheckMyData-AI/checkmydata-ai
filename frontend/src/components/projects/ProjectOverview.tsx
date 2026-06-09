"use client";

import { useMemo } from "react";
import { ConnectionHealth } from "@/components/connections/ConnectionHealth";
import { SyncStatusIndicator } from "@/components/connections/SyncStatusIndicator";
import { KnowledgeHealthPanel } from "@/components/knowledge/KnowledgeHealthPanel";
import { UsageStatsPanel } from "@/components/usage/UsageStatsPanel";
import { useAppStore } from "@/stores/app-store";
import { useLogStore } from "@/stores/log-store";
import { Icon } from "@/components/ui/Icon";

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function ProjectOverview() {
  const activeProject = useAppStore((s) => s.activeProject);
  const activeConnection = useAppStore((s) => s.activeConnection);
  const connections = useAppStore((s) => s.connections);
  const entries = useLogStore((s) => s.entries);

  const recentErrors = useMemo(
    () =>
      entries
        .filter((e) => e.status === "failed")
        .slice(-5)
        .reverse(),
    [entries],
  );

  if (!activeProject) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="text-center max-w-sm">
          <Icon name="folder-git" size={32} className="mx-auto text-text-muted mb-3" />
          <p className="text-sm text-text-secondary">Select a project to see its overview</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6 space-y-6">
        <div>
          <h2 className="text-sm font-semibold text-text-primary">{activeProject.name}</h2>
          <p className="text-xs text-text-tertiary mt-0.5">Project overview and health</p>
        </div>

        <section className="rounded-lg border border-border-subtle bg-surface-1/50 p-4 space-y-3">
          <h3 className="text-xs font-medium text-text-secondary uppercase tracking-wider">
            Connection Health
          </h3>
          {activeConnection ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs text-text-primary">
                <Icon name="database" size={14} className="text-text-tertiary" />
                <span>{activeConnection.name}</span>
                <span className="text-[10px] text-text-muted uppercase font-mono">
                  {activeConnection.db_type}
                </span>
              </div>
              <ConnectionHealth connectionId={activeConnection.id} />
              <SyncStatusIndicator />
            </div>
          ) : connections.length > 0 ? (
            <p className="text-xs text-text-tertiary">Select a connection from the sidebar</p>
          ) : (
            <p className="text-xs text-text-tertiary">No connections configured yet</p>
          )}
        </section>

        <KnowledgeHealthPanel
          projectId={activeProject.id}
          connectionId={activeConnection?.id ?? null}
        />

        <section className="rounded-lg border border-border-subtle bg-surface-1/50 p-4 space-y-3">
          <h3 className="text-xs font-medium text-text-secondary uppercase tracking-wider">
            Recent Errors
          </h3>
          {recentErrors.length === 0 ? (
            <p className="text-xs text-text-tertiary">No recent pipeline errors</p>
          ) : (
            <ul className="space-y-2">
              {recentErrors.map((entry) => (
                <li
                  key={entry.id}
                  className="flex items-start gap-2 text-xs border border-border-subtle rounded-md px-2.5 py-2 bg-surface-0/50"
                >
                  <Icon name="alert-triangle" size={12} className="text-error shrink-0 mt-0.5" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-text-secondary">
                      <span className="font-mono text-[10px] text-text-muted">
                        {formatTime(entry.timestamp)}
                      </span>
                      <span className="text-[10px] uppercase text-text-tertiary">
                        {entry.pipeline}
                      </span>
                    </div>
                    <p className="text-text-primary truncate mt-0.5">
                      {entry.detail || entry.step}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-lg border border-border-subtle bg-surface-1/50 p-4 space-y-3">
          <h3 className="text-xs font-medium text-text-secondary uppercase tracking-wider">
            Usage Summary
          </h3>
          <UsageStatsPanel compact />
        </section>
      </div>
    </div>
  );
}
