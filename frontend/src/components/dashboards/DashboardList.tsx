"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import type { Dashboard } from "@/lib/api";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";
import { Icon } from "@/components/ui/Icon";
import { FormModal } from "@/components/ui/FormModal";
import { DashboardBuilder } from "./DashboardBuilder";

interface DashboardListProps {
  createRequested?: boolean;
  onCreateHandled?: () => void;
}

export function DashboardList({ createRequested, onCreateHandled }: DashboardListProps) {
  const activeProject = useAppStore((s) => s.activeProject);
  const router = useRouter();
  const [dashboards, setDashboards] = useState<Dashboard[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (createRequested) {
      setCreating(true);
      onCreateHandled?.();
    }
  }, [createRequested, onCreateHandled]);

  const load = useCallback(async (signal?: { cancelled: boolean }) => {
    if (!activeProject) return;
    setLoading(true);
    setLoadError(false);
    try {
      const list = await api.dashboards.list(activeProject.id);
      if (signal?.cancelled) return;
      setDashboards(list);
    } catch {
      if (signal?.cancelled) return;
      setDashboards([]);
      setLoadError(true);
    } finally {
      if (!signal?.cancelled) setLoading(false);
    }
  }, [activeProject]);

  useEffect(() => {
    const signal = { cancelled: false };
    load(signal);
    return () => { signal.cancelled = true; };
  }, [load]);

  const handleCreated = (d: Dashboard) => {
    setCreating(false);
    setDashboards((prev) => [d, ...prev]);
    router.push(`/dashboard/${d.id}`);
  };

  return (
    <div className="px-1 space-y-1">
      <FormModal
        open={creating}
        onClose={() => setCreating(false)}
        title="New Dashboard"
        maxWidth="max-w-2xl"
      >
        <DashboardBuilder onSave={handleCreated} onCancel={() => setCreating(false)} />
      </FormModal>
      {loading ? (
        <div className="flex justify-center py-3">
          <div className="w-4 h-4 border-2 border-accent border-t-transparent rounded-full animate-spin" />
        </div>
      ) : loadError ? (
        <div className="px-2 py-2 text-center">
          <p className="text-[10px] text-text-muted">Couldn&apos;t load dashboards</p>
          <button
            onClick={() => load()}
            className="text-[10px] text-accent hover:text-accent-hover transition-colors mt-1"
          >
            Retry
          </button>
        </div>
      ) : dashboards.length === 0 ? (
        <p className="text-[10px] text-text-muted px-2 py-2">No dashboards yet</p>
      ) : (
        dashboards.map((d) => (
          <button
            key={d.id}
            onClick={() => router.push(`/dashboard/${d.id}`)}
            className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-left hover:bg-surface-1 transition-colors group"
          >
            <Icon name="layout" size={12} className="text-text-tertiary shrink-0" />
            <span className="text-[11px] text-text-secondary group-hover:text-text-primary truncate flex-1">
              {d.title}
            </span>
            {d.is_shared && (
              <Icon name="users" size={10} className="text-text-muted shrink-0" />
            )}
          </button>
        ))
      )}
    </div>
  );
}
