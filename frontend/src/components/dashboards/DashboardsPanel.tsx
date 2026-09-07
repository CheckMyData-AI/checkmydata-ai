"use client";

import { DashboardList } from "./DashboardList";
import { useAppStore } from "@/stores/app-store";

/**
 * Dashboards as a screen.
 *
 * They had no panel at all: the only way to reach one was a collapsible section in the
 * left rail, which is why the rail had thirteen of them. A destination here is what
 * lets the rail become navigation instead of being the product's only surface.
 */
export function DashboardsPanel() {
  const activeProject = useAppStore((s) => s.activeProject);

  if (!activeProject) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <p className="text-sm text-text-tertiary">Select a project first</p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6 space-y-4">
        <div className="animate-slide-in-left" style={{ animationFillMode: "both" }}>
          <h2 className="text-sm font-semibold text-text-primary">Dashboards</h2>
          <p className="text-xs text-text-tertiary mt-0.5">
            Saved views for {activeProject.name}
          </p>
        </div>
        <section
          className="animate-slide-in-left rounded-card border border-border bg-panel p-4"
          style={{ animationDelay: "60ms", animationFillMode: "both" }}
        >
          <DashboardList />
        </section>
      </div>
    </div>
  );
}
