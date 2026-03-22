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
      <div className="flex-1 flex items-center justify-center text-zinc-500 text-sm">
        Checking project readiness...
      </div>
    );
  }

  if (fetchError) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="max-w-sm w-full mx-4 bg-zinc-800/50 border border-red-700/30 rounded-xl p-6 space-y-3 text-center">
          <p className="text-sm text-red-400">Failed to check project readiness</p>
          <div className="flex gap-2 justify-center">
            <button
              onClick={() => { setLoading(true); fetchReadiness(); }}
              className="text-sm px-4 py-2 rounded-lg bg-zinc-700 text-zinc-300 hover:bg-zinc-600 transition-colors"
            >
              Retry
            </button>
            <button
              onClick={onBypass}
              className="text-sm px-4 py-2 rounded-lg bg-zinc-700 text-zinc-300 hover:bg-zinc-600 transition-colors"
            >
              Chat anyway
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!readiness) {
    onBypass();
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
      <div className="max-w-md w-full mx-4 bg-zinc-800/50 border border-zinc-700 rounded-xl p-6 space-y-4">
        <h3 className="text-sm font-medium text-zinc-200">
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
                <span className={`w-2 h-2 rounded-full shrink-0 ${done ? "bg-green-400" : "bg-zinc-600"}`} />
                {isNavigable ? (
                  <button
                    onClick={() => handleNavigate(step)}
                    className="flex-1 text-sm text-left text-blue-400 hover:text-blue-300 hover:underline cursor-pointer transition-colors"
                  >
                    {STEP_LABELS[step] || step}
                    <span className="ml-1.5 text-[10px] opacity-60">→</span>
                  </button>
                ) : (
                  <span className={`flex-1 text-sm ${done ? "text-zinc-300" : "text-zinc-500"}`}>
                    {STEP_LABELS[step] || step}
                  </span>
                )}
                {done && (
                  <span className="text-[10px] text-green-400/70 shrink-0">Done</span>
                )}
                {canAct && (
                  <button
                    onClick={() => handleAction(step)}
                    disabled={isRunning || !prevDone}
                    className="text-[10px] px-2 py-1 rounded bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isRunning ? "Running..." : "Run"}
                  </button>
                )}
              </div>
            );
          })}
        </div>

        {readiness.last_indexed_at && (
          <div className="text-[11px] text-zinc-500">
            Last indexed {timeAgo(readiness.last_indexed_at)}
            {readiness.commits_behind > 0 && (
              <span className="text-amber-400/80 ml-1">
                · {readiness.commits_behind} new commit{readiness.commits_behind !== 1 ? "s" : ""}
              </span>
            )}
          </div>
        )}

        {readiness.is_stale && (
          <div className="flex items-center gap-2 p-2.5 rounded-lg bg-amber-900/20 border border-amber-800/30">
            <span className="text-xs text-amber-400">
              Index is outdated ({">"} 7 days, {readiness.commits_behind} new commits). Re-indexing recommended.
            </span>
            <button
              onClick={() => handleAction("index_repo")}
              disabled={actionInProgress === "index_repo"}
              className="shrink-0 text-[10px] px-2 py-1 rounded bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-50"
            >
              {actionInProgress === "index_repo" ? "Running..." : "Re-index"}
            </button>
          </div>
        )}

        {!allDone && (
          <div className="border-t border-zinc-700 pt-3 space-y-2">
            <p className="text-xs text-amber-400/80">
              You can still chat, but SQL queries may be less accurate without full setup.
            </p>
            <button
              onClick={onBypass}
              className="w-full text-sm px-4 py-2 rounded-lg bg-zinc-700 text-zinc-300 hover:bg-zinc-600 transition-colors"
            >
              Chat anyway
            </button>
          </div>
        )}

        {allDone && !readiness.is_stale && (
          <div className="border-t border-zinc-700 pt-3">
            <button
              onClick={onBypass}
              className="w-full text-sm px-4 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-500 transition-colors"
            >
              Start chatting
            </button>
          </div>
        )}

        {allDone && readiness.is_stale && (
          <div className="border-t border-zinc-700 pt-3">
            <button
              onClick={onBypass}
              className="w-full text-sm px-4 py-2 rounded-lg bg-zinc-700 text-zinc-300 hover:bg-zinc-600 transition-colors"
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
    <div className="flex items-center gap-2 px-6 py-1.5 bg-amber-900/20 border-b border-amber-800/30 text-xs text-amber-400">
      {missing.length > 0 && <span>Missing: {missing.join(" → ")}</span>}
      {missing.length > 0 && staleInfo?.is_stale && <span>·</span>}
      {staleInfo?.is_stale && (
        <span>Index outdated ({staleInfo.commits_behind} new commits)</span>
      )}
    </div>
  );
}
