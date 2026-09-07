"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type AttentionItem, type AttentionResponse } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { useAppPanel, isAppPanel } from "@/hooks/useAppPanel";
import { Icon } from "@/components/ui/Icon";

/**
 * What needs the user, at the top of the rail. `SCN-150`.
 *
 * Three rules this component exists to keep, each with a failure mode that reads as
 * success:
 *
 * **Absent, not empty.** With nothing to report the group renders `null` — no header,
 * no "all good" box. A permanent green panel is one people stop reading, and the whole
 * value here is that its presence means something.
 *
 * **"Could not check" is not "nothing needs you".** When the backend reports a degraded
 * source the group renders, saying so. Those two must never look alike, and the version
 * that drops the failure is the one that looks fine and is wrong.
 *
 * **Every entry goes somewhere.** An item the user can read but not act on is a
 * complaint. Each carries the panel that fixes it and clicking navigates there.
 */

const SEVERITY_STYLE: Record<string, { dot: string; label: string }> = {
  critical: { dot: "bg-danger", label: "critical" },
  warning: { dot: "bg-warning", label: "warning" },
  info: { dot: "bg-text-muted", label: "info" },
};

function relative(at: string | null): string {
  if (!at) return "";
  const then = new Date(at).getTime();
  if (Number.isNaN(then)) return "";
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function AttentionGroup() {
  const activeProject = useAppStore((s) => s.activeProject);
  const { setPanel } = useAppPanel();
  const [data, setData] = useState<AttentionResponse | null>(null);
  const [failed, setFailed] = useState(false);

  const projectId = activeProject?.id;

  useEffect(() => {
    if (!projectId) {
      setData(null);
      return;
    }
    let cancelled = false;
    setFailed(false);
    api.projects
      .attention(projectId)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch(() => {
        // The request itself failing is the same class as a degraded source: it must
        // not render as "nothing needs you".
        if (!cancelled) {
          setData(null);
          setFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const go = useCallback(
    (item: AttentionItem) => {
      const name = item.route.startsWith("panel=") ? item.route.slice(6) : item.route;
      if (isAppPanel(name)) setPanel(name);
    },
    [setPanel],
  );

  if (!projectId) return null;

  const items = data?.items ?? [];
  const degraded = failed ? ["everything"] : (data?.degraded ?? []);

  // Absent, not empty. Nothing to say means nothing rendered.
  if (items.length === 0 && degraded.length === 0) return null;

  return (
    <div className="mx-1 mb-1" data-testid="attention-group">
      <div className="flex items-center gap-2 px-2 py-1.5">
        <span className="text-kicker uppercase tracking-wider text-text-muted font-medium">
          Needs you
        </span>
        {items.length > 0 && (
          <span className="text-kicker text-text-muted">({items.length})</span>
        )}
      </div>

      <div className="space-y-0.5">
        {items.map((item, i) => (
          <button
            key={`${item.kind}-${item.subject}-${i}`}
            type="button"
            onClick={() => go(item)}
            className="w-full text-left px-2 py-1.5 rounded-lg hover:bg-surface-1 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <span className="flex items-start gap-2">
              <span
                aria-hidden="true"
                className={`mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 ${
                  SEVERITY_STYLE[item.severity]?.dot ?? "bg-text-muted"
                }`}
              />
              <span className="min-w-0 flex-1">
                <span className="block text-xs text-text-secondary truncate">
                  {item.subject}
                </span>
                <span className="block text-meta text-text-muted">
                  {item.what}
                  {item.at ? ` · ${relative(item.at)}` : ""}
                </span>
              </span>
            </span>
          </button>
        ))}

        {(data?.more ?? 0) > 0 && (
          <button
            type="button"
            onClick={() => setPanel("logs")}
            className="w-full text-left px-2 py-1 text-meta text-text-muted hover:text-text-secondary transition-colors"
          >
            {data?.more} more →
          </button>
        )}

        {degraded.length > 0 && (
          <p className="px-2 py-1 text-meta text-text-muted flex items-center gap-1.5">
            <Icon name="alert-triangle" size={11} className="shrink-0" />
            Could not check {degraded.join(", ")}
          </p>
        )}
      </div>
    </div>
  );
}
