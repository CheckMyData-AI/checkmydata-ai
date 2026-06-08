"use client";

import { ConnectionSelector } from "@/components/connections/ConnectionSelector";
import { SyncStatusIndicator } from "@/components/connections/SyncStatusIndicator";
import { useAppStore } from "@/stores/app-store";
import { Icon } from "@/components/ui/Icon";

export function ConnectionsPanel() {
  const activeProject = useAppStore((s) => s.activeProject);
  const connections = useAppStore((s) => s.connections);

  if (!activeProject) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <p className="text-sm text-text-tertiary">Select a project first</p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-xl mx-auto p-6 space-y-4">
        <div>
          <h2 className="text-sm font-semibold text-text-primary">Connections</h2>
          <p className="text-xs text-text-tertiary mt-0.5">
            Database connections for {activeProject.name}
          </p>
        </div>
        <section className="rounded-lg border border-border-subtle bg-surface-1/50 p-3">
          <div className="flex items-center gap-2 mb-2 px-1">
            <Icon name="database" size={14} className="text-text-tertiary" />
            <span className="text-xs text-text-secondary">
              {connections.length} connection{connections.length !== 1 ? "s" : ""}
            </span>
          </div>
          <ConnectionSelector />
          <SyncStatusIndicator />
        </section>
      </div>
    </div>
  );
}
