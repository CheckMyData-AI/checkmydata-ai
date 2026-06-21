"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type KnowledgeHealth, type KnowledgeActionKind } from "@/lib/api";
import { POLL_INTERVAL_MS } from "@/lib/polling";
import { useAppStore } from "@/stores/app-store";
import { Icon } from "@/components/ui/Icon";
import { Tooltip } from "@/components/ui/Tooltip";
import { toast } from "@/stores/toast-store";
import { SyncHistoryPanel } from "@/components/knowledge/SyncHistoryPanel";

interface KnowledgeHealthPanelProps {
  projectId: string;
  connectionId: string | null;
}

const COUNT_META: { key: keyof KnowledgeHealth["artifact_counts"]; label: string; icon: Parameters<typeof Icon>[0]["name"] }[] = [
  { key: "tables", label: "Tables", icon: "database" },
  { key: "lineage", label: "Lineage", icon: "git-branch" },
  { key: "learnings", label: "Learnings", icon: "book-open" },
  { key: "insights", label: "Insights", icon: "layers" },
  { key: "rules", label: "Rules", icon: "check" },
];

const SEVERITY_STYLES: Record<string, string> = {
  info: "border-border-subtle bg-surface-0/50 text-text-secondary",
  warning: "border-border-default bg-warning-muted text-warning",
  critical: "border-border-default bg-error-muted text-error",
};

export function KnowledgeHealthPanel({ projectId, connectionId }: KnowledgeHealthPanelProps) {
  const [health, setHealth] = useState<KnowledgeHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [actionRunning, setActionRunning] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const fetchHealth = useCallback(async () => {
    try {
      setError(false);
      const h = await api.projects.knowledgeHealth(projectId, connectionId);
      if (mountedRef.current) setHealth(h);
    } catch {
      if (mountedRef.current) setError(true);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [projectId, connectionId]);

  useEffect(() => {
    setLoading(true);
    fetchHealth();
  }, [fetchHealth]);

  const pipelineStatus = useAppStore((s) => s.pipelineStatusByProject[projectId]);
  const anyPipelineRunning = pipelineStatus?.any_running ?? false;

  useEffect(() => {
    if (!anyPipelineRunning) return;
    const id = setInterval(() => {
      void fetchHealth();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [anyPipelineRunning, fetchHealth]);

  const runAction = async (
    kind: KnowledgeActionKind,
    actionConnId: string | null,
    key: string,
  ) => {
    const cid = actionConnId || connectionId;
    setActionRunning(key);
    try {
      if (kind === "reindex_db" && cid) {
        await api.connections.indexDb(cid);
        toast("Database indexing started", "success");
      } else if (kind === "resync" && cid) {
        await api.connections.triggerSync(cid);
        toast("Code-DB sync started", "success");
      } else if (kind === "reindex_repo") {
        await api.repos.index(projectId);
        toast("Repository indexing started", "success");
      } else {
        setActionRunning(null);
        return;
      }
      // Re-poll once shortly after so the panel reflects the new running state.
      setTimeout(() => {
        if (mountedRef.current) fetchHealth();
      }, 1500);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Action failed", "error");
    } finally {
      if (mountedRef.current) setActionRunning(null);
    }
  };

  return (
    <>
    <SyncHistoryPanel projectId={projectId} />
    <section className="rounded-lg border border-border-subtle bg-surface-1/50 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-text-secondary uppercase tracking-wider">
          Knowledge Health
        </h3>
        <Tooltip label="Refresh">
          <button
            onClick={() => {
              setLoading(true);
              fetchHealth();
            }}
            aria-label="Refresh knowledge health"
            className="text-text-tertiary hover:text-text-primary transition-colors"
          >
            <Icon name="refresh-cw" size={13} />
          </button>
        </Tooltip>
      </div>

      {loading ? (
        <p className="text-xs text-text-tertiary">Checking knowledge freshness…</p>
      ) : error ? (
        <div className="flex items-center gap-2 text-xs text-error">
          <Icon name="alert-triangle" size={12} />
          <span>Could not load knowledge health</span>
        </div>
      ) : !health ? null : (
        <div className="space-y-3">
          {anyPipelineRunning && (
            <div className="flex items-center gap-2 text-xs text-warning rounded-md border border-border-default bg-warning-muted px-2.5 py-2">
              <span className="w-1.5 h-1.5 rounded-full bg-warning animate-pulse-dot shrink-0" />
              <span>Knowledge pipeline running (index or sync in progress)…</span>
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {COUNT_META.map(({ key, label, icon }) => (
              <div
                key={key}
                className="flex items-center gap-1.5 rounded-md border border-border-subtle bg-surface-0/50 px-2.5 py-1.5"
              >
                <Icon name={icon} size={12} className="text-text-tertiary" />
                <span className="text-xs font-mono text-text-primary">
                  {health.artifact_counts[key]}
                </span>
                <span className="text-[10px] text-text-tertiary">{label}</span>
              </div>
            ))}
          </div>

          {!health.freshness.overall_stale ? (
            <div className="flex items-center gap-2 text-xs text-success">
              <Icon name="check" size={13} />
              <span>Everything is fresh</span>
            </div>
          ) : (
            <ul className="space-y-2">
              {health.freshness.warnings.map((w, idx) => {
                const action = w.recommended_action;
                const actionable = action.kind !== "none";
                const key = `${w.category}-${idx}`;
                const running = actionRunning === key;
                return (
                  <li
                    key={key}
                    className={`flex items-start gap-2 rounded-md border px-2.5 py-2 ${
                      SEVERITY_STYLES[w.severity] || SEVERITY_STYLES.warning
                    }`}
                  >
                    <Icon name="alert-triangle" size={12} className="shrink-0 mt-0.5" />
                    <span className="min-w-0 flex-1 text-xs leading-relaxed">{w.message}</span>
                    {actionable && (
                      <button
                        onClick={() => runAction(action.kind, action.connection_id, key)}
                        disabled={running}
                        className="shrink-0 text-[10px] px-2 py-1 rounded bg-accent text-white hover:bg-accent-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {running ? "Running…" : action.label}
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </section>
    </>
  );
}
