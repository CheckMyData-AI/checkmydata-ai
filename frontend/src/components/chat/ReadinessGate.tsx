"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { api, type ProjectReadiness } from "@/lib/api";
import { useLogStore } from "@/stores/log-store";
import { useAppStore } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";
import { POLL_INTERVAL_MS, MAX_POLL_MS } from "@/lib/polling";

interface ReadinessGateProps {
  projectId: string;
  connectionId: string | null;
  onBypass: () => void;
}

const STEP_LABELS: Record<string, string> = {
  connect_repo: "Git repository",
  index_repo: "Repository indexed",
  connect_db: "Database connection",
  index_db: "Database indexed",
  sync: "Code ↔ DB synced",
};

const STEP_LABELS_ACTION: Record<string, string> = {
  index_repo: "Index the repository",
  index_db: "Index the database",
  sync: "Sync code ↔ database",
};

const NAVIGABLE_STEPS: Record<string, { section: string; editProject?: boolean }> = {
  connect_repo: { section: "projects", editProject: true },
  connect_db: { section: "connections" },
};

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

export function ReadinessGate({ projectId, connectionId, onBypass }: ReadinessGateProps) {
  const cachedReady = useAppStore((s) => s.readinessCache[projectId]?.ready);
  const [readiness, setReadiness] = useState<ProjectReadiness | null>(null);
  const [loading, setLoading] = useState(!cachedReady);
  const [fetchError, setFetchError] = useState(false);
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const fetchReadiness = useCallback(async () => {
    try {
      setFetchError(false);
      const r = await api.projects.readiness(projectId);
      if (!mountedRef.current) return;
      setReadiness(r);
      useAppStore.getState().setReadinessCache(projectId, {
        ready: r.ready,
        checkedAt: Date.now(),
      });
      if (r.ready && !r.is_stale) {
        onBypass();
      }
    } catch {
      if (mountedRef.current) setFetchError(true);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [projectId, onBypass]);

  useEffect(() => {
    if (cachedReady) {
      fetchReadiness();
    } else {
      fetchReadiness();
    }
  }, [fetchReadiness, connectionId, cachedReady]);

  const startPolling = useCallback((stepKey: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    const start = Date.now();
    pollRef.current = setInterval(async () => {
      if (Date.now() - start > MAX_POLL_MS) {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        if (mountedRef.current) {
          setActionInProgress(null);
          toast(`${STEP_LABELS_ACTION[stepKey] || stepKey} timed out`, "error");
        }
        return;
      }
      try {
        const r = await api.projects.readiness(projectId);
        if (!mountedRef.current) return;
        setReadiness(r);
        useAppStore.getState().setReadinessCache(projectId, {
          ready: r.ready,
          checkedAt: Date.now(),
        });
        const stepDone =
          (stepKey === "index_repo" && r.repo_indexed) ||
          (stepKey === "index_db" && r.db_indexed) ||
          (stepKey === "sync" && r.code_db_synced);
        if (stepDone) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setActionInProgress(null);
          toast(`${STEP_LABELS_ACTION[stepKey] || stepKey} completed`, "success");
        }
      } catch {
        /* poll silently */
      }
    }, POLL_INTERVAL_MS);
  }, [projectId]);

  useEffect(() => {
    if (!loading && !fetchError && !readiness) {
      onBypass();
    }
  }, [loading, fetchError, readiness, onBypass]);

  const handleAction = async (step: string) => {
    const cid = connectionId || readiness?.active_connection_id;
    setActionInProgress(step);
    try {
      if (step === "index_repo") {
        await api.repos.index(projectId);
        toast("Repository indexing started", "success");
      } else if (step === "index_db" && cid) {
        await api.connections.indexDb(cid);
        toast("Database indexing started", "success");
      } else if (step === "sync" && cid) {
        await api.connections.triggerSync(cid);
        toast("Code-DB sync started", "success");
      }
      startPolling(step);
      useLogStore.getState().setOpen(true);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Action failed", "error");
      setActionInProgress(null);
    }
  };

  if (cachedReady && loading) {
    return null;
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-text-tertiary text-sm">
        Checking project readiness...
      </div>
    );
  }

  if (fetchError) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="max-w-sm w-full mx-4 bg-surface-2/50 border border-border-default rounded-xl p-6 space-y-3 text-center">
          <p className="text-sm text-error">Failed to check project readiness</p>
          <div className="flex gap-2 justify-center">
            <button
              onClick={() => { setLoading(true); fetchReadiness(); }}
              className="text-sm px-4 py-2 rounded-lg bg-surface-3 text-text-primary hover:bg-surface-3 transition-colors"
            >
              Retry
            </button>
            <button
              onClick={onBypass}
              className="text-sm px-4 py-2 rounded-lg bg-surface-3 text-text-primary hover:bg-surface-3 transition-colors"
            >
              Chat anyway
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!readiness) {
    return null;
  }

  const allSteps = ["connect_repo", "index_repo", "connect_db", "index_db", "sync"];
  const actionableSteps = new Set(["index_repo", "index_db", "sync"]);

  const stepDone: Record<string, boolean> = {
    connect_repo: readiness.repo_connected,
    index_repo: readiness.repo_indexed,
    connect_db: readiness.db_connected,
    index_db: readiness.db_indexed,
    sync: readiness.code_db_synced,
  };

  const handleNavigate = (step: string) => {
    const nav = NAVIGABLE_STEPS[step];
    if (!nav) return;
    const store = useAppStore.getState();
    store.setFocusSidebarSection(nav.section);
    if (nav.editProject) {
      store.setTriggerProjectEdit(true);
    }
  };

  const allDone = readiness.ready;

  return (
    <div className="flex-1 flex items-center justify-center">
        <div className="max-w-md w-full mx-4 bg-surface-2/50 border border-border-default rounded-xl p-6 space-y-4">
        <h3 className="text-sm font-medium text-text-primary">
          {allDone ? "Project status" : "Set up your project for full AI queries"}
        </h3>

        <div className="space-y-1.5">
          {allSteps.map((step, idx) => {
            const done = stepDone[step];
            const canAct = actionableSteps.has(step) && !done;
            const prevDone = idx === 0 || stepDone[allSteps[idx - 1]];
            const isRunning = actionInProgress === step;
            const isNavigable = !done && step in NAVIGABLE_STEPS;

            return (
              <div key={step} className="flex items-center gap-3 py-1">
                <span className={`w-2 h-2 rounded-full shrink-0 ${done ? "bg-success" : "bg-surface-3"}`} />
                {isNavigable ? (
                  <button
                    onClick={() => handleNavigate(step)}
                    className="flex-1 text-sm text-left text-accent hover:text-accent-hover hover:underline cursor-pointer transition-colors"
                  >
                    {STEP_LABELS[step] || step}
                    <span className="ml-1.5 text-[10px] opacity-60">→</span>
                  </button>
                ) : (
                  <span className={`flex-1 text-sm ${done ? "text-text-primary" : "text-text-tertiary"}`}>
                    {STEP_LABELS[step] || step}
                  </span>
                )}
                {done && (
                  <span className="text-[10px] text-success/70 shrink-0">Done</span>
                )}
                {canAct && (
                  <button
                    onClick={() => handleAction(step)}
                    disabled={isRunning || !prevDone}
                    className="text-[10px] px-2 py-1 rounded bg-accent text-white hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isRunning ? "Running..." : "Run"}
                  </button>
                )}
              </div>
            );
          })}
        </div>

        {readiness.last_indexed_at && (
          <div className="text-[11px] text-text-tertiary">
            Last indexed {timeAgo(readiness.last_indexed_at)}
            {readiness.commits_behind > 0 && (
              <span className="text-warning/80 ml-1">
                · {readiness.commits_behind} new commit{readiness.commits_behind !== 1 ? "s" : ""}
              </span>
            )}
          </div>
        )}

        {readiness.is_stale && (
          <div className="flex items-center gap-2 p-2.5 rounded-lg bg-warning-muted border border-border-default">
            <span className="text-xs text-warning">
              Index is outdated ({">"} 7 days, {readiness.commits_behind} new commits). Re-indexing recommended.
            </span>
            <button
              onClick={() => handleAction("index_repo")}
              disabled={actionInProgress === "index_repo"}
              className="shrink-0 text-[10px] px-2 py-1 rounded bg-warning text-white hover:bg-warning disabled:opacity-50"
            >
              {actionInProgress === "index_repo" ? "Running..." : "Re-index"}
            </button>
          </div>
        )}

        {!allDone && (
          <div className="border-t border-border-default pt-3 space-y-2">
            <p className="text-xs text-warning/80">
              You can still chat, but SQL queries may be less accurate without full setup.
            </p>
            <button
              onClick={onBypass}
              className="w-full text-sm px-4 py-2 rounded-lg bg-surface-3 text-text-primary hover:bg-surface-3 transition-colors"
            >
              Chat anyway
            </button>
          </div>
        )}

        {allDone && !readiness.is_stale && (
          <div className="border-t border-border-default pt-3">
            <button
              onClick={onBypass}
              className="w-full text-sm px-4 py-2 rounded-lg bg-accent text-white hover:bg-accent-hover transition-colors"
            >
              Start chatting
            </button>
          </div>
        )}

        {allDone && readiness.is_stale && (
          <div className="border-t border-border-default pt-3">
            <button
              onClick={onBypass}
              className="w-full text-sm px-4 py-2 rounded-lg bg-surface-3 text-text-primary hover:bg-surface-3 transition-colors"
            >
              Chat anyway
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export function ReadinessBanner({ projectId }: { projectId: string }) {
  const [missing, setMissing] = useState<string[]>([]);
  const [staleInfo, setStaleInfo] = useState<{ is_stale: boolean; commits_behind: number } | null>(null);
  const bannerMountedRef = useRef(true);

  useEffect(() => {
    bannerMountedRef.current = true;
    return () => { bannerMountedRef.current = false; };
  }, []);

  useEffect(() => {
    api.projects.readiness(projectId).then((r) => {
      if (!bannerMountedRef.current) return;
      if (!r.ready) {
        setMissing(r.missing_steps.map((s) => s.label));
      } else {
        setMissing([]);
      }
      if (r.is_stale) {
        setStaleInfo({ is_stale: r.is_stale, commits_behind: r.commits_behind });
      } else {
        setStaleInfo(null);
      }
    }).catch(() => {
      if (bannerMountedRef.current) {
        setMissing([]);
        toast("Could not check project readiness", "error");
      }
    });
  }, [projectId]);

  if (missing.length === 0 && !staleInfo?.is_stale) return null;

  return (
    <div className="flex items-center gap-2 px-6 py-1.5 bg-warning-muted border-b border-border-default text-xs text-warning">
      {missing.length > 0 && <span>Missing: {missing.join(" → ")}</span>}
      {missing.length > 0 && staleInfo?.is_stale && <span>·</span>}
      {staleInfo?.is_stale && (
        <span>Index outdated ({staleInfo.commits_behind} new commits)</span>
      )}
    </div>
  );
}
