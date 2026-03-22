"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import type { Dashboard } from "@/lib/api";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";
import { Icon } from "@/components/ui/Icon";
import { DashboardBuilder } from "./DashboardBuilder";

export function DashboardList() {
  const activeProject = useAppStore((s) => s.activeProject);
  const router = useRouter();
  const [dashboards, setDashboards] = useState<Dashboard[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async (signal?: { cancelled: boolean }) => {
    if (!activeProject) return;
    setLoading(true);
    try {
      const list = await api.dashboards.list(activeProject.id);
      if (signal?.cancelled) return;
      setDashboards(list);
    } catch {
      if (signal?.cancelled) return;
      setDashboards([]);
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

  if (creating) {
    return (
      <div className="px-2 py-1">
        <DashboardBuilder onSave={handleCreated} onCancel={() => setCreating(false)} />
      </div>
    );
  }

  return (
    <div className="px-1 space-y-1">
      <button
        onClick={() => setCreating(true)}
        className="w-full flex items-center gap-1.5 px-2 py-1.5 text-[11px] text-text-muted hover:text-text-secondary hover:bg-surface-1 rounded transition-colors"
      >
        <Icon name="plus" size={11} />
        New Dashboard
      </button>

      {loading ? (
        <div className="flex justify-center py-3">
          <div className="w-4 h-4 border-2 border-accent border-t-transparent rounded-full animate-spin" />
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
