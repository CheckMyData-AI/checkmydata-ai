"use client";

import { useAppStore } from "@/stores/app-store";
import { useAppPanel } from "@/hooks/useAppPanel";
import { Icon } from "@/components/ui/Icon";

/**
 * The rail's sources: **selection, and nothing else**. `SCN-133`, `SCN-149`.
 *
 * Which source a question runs against is a thing you switch while working, so it
 * belongs in the rail. Creating, editing, testing, indexing and deleting one are things
 * you do deliberately, so they belong on the screen built for them — and having both
 * here is what made a rail of thirteen collapsible sections in the first place.
 *
 * The rule this component exists to keep: **exactly one place manages a source, and
 * exactly one place switches between them, and they are not the same place.** A
 * "Manage" link is the seam between the two, so the rail never has to grow a form.
 */
export function RailSourceList() {
  const connections = useAppStore((s) => s.connections);
  const activeConnection = useAppStore((s) => s.activeConnection);
  const setActiveConnection = useAppStore((s) => s.setActiveConnection);
  const { setPanel } = useAppPanel();

  if (connections.length === 0) {
    return (
      <div className="px-3 py-2">
        <button
          type="button"
          onClick={() => setPanel("connections")}
          className="text-meta text-text-tertiary hover:text-text-secondary transition-colors underline outline-none focus-visible:ring-2 focus-visible:ring-accent rounded"
        >
          Connect a data source
        </button>
      </div>
    );
  }

  return (
    <div className="px-1 py-0.5 space-y-0.5">
      {connections.map((c) => {
        const active = activeConnection?.id === c.id;
        return (
          <button
            key={c.id}
            type="button"
            onClick={() => setActiveConnection(c)}
            aria-current={active ? "true" : undefined}
            className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent ${
              active
                ? "bg-surface-1 text-text-primary"
                : "text-text-secondary hover:bg-surface-1"
            }`}
          >
            <Icon name="database" size={13} className="text-text-tertiary shrink-0" />
            <span className="text-xs truncate">{c.name}</span>
          </button>
        );
      })}
      <button
        type="button"
        onClick={() => setPanel("connections")}
        className="w-full text-left px-2 py-1 text-meta text-text-muted hover:text-text-secondary transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent rounded"
      >
        Manage sources →
      </button>
    </div>
  );
}
