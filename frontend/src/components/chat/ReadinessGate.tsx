"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { api, type ProjectReadiness } from "@/lib/api";
import { useLogStore } from "@/stores/log-store";
import { useAppStore } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";

interface ReadinessGateProps {
  projectId: string;
  connectionId: string | null;
  onBypass: () => void;
}

const STEP_LABELS: Record<string, string> = {
  connect_repo: "Connect a Git repository",
  index_repo: "Index the repository",
  connect_db: "Add a database connection",
  index_db: "Index the database",
  sync: "Sync code ↔ database",
};

const NAVIGABLE_STEPS: Record<string, { section: string; editProject?: boolean }> = {
  connect_repo: { section: "projects", editProject: true },
  connect_db: { section: "connections" },
};

const POLL_INTERVAL_MS = 4000;
const MAX_POLL_MS = 10 * 60 * 1000;

export function ReadinessGate({ projectId, connectionId, onBypass }: ReadinessGateProps) {
  const [readiness, setReadiness] = useState<ProjectReadiness | null>(null);
  const [loading, setLoading] = useState(true);
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
      if (mountedRef.current) setReadiness(r);
    } catch {
      if (mountedRef.current) setFetchError(true);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    fetchReadiness();
  }, [fetchReadiness, connectionId]);

  const startPolling = useCallback((stepKey: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    const start = Date.now();
    pollRef.current = setInterval(async () => {
      if (Date.now() - start > MAX_POLL_MS) {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        if (mountedRef.current) {
          setActionInProgress(null);
          toast(`${STEP_LABELS[stepKey] || stepKey} timed out`, "error");
        }
        return;
      }
      try {
        const r = await api.projects.readiness(projectId);
        if (!mountedRef.current) return;
        setReadiness(r);
        const stepDone =
          (stepKey === "index_repo" && r.repo_indexed) ||
          (stepKey === "index_db" && r.db_indexed) ||
          (stepKey === "sync" && r.code_db_synced);
        if (stepDone) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setActionInProgress(null);
          toast(`${STEP_LABELS[stepKey] || stepKey} completed`, "success");
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

  if (!readiness || readiness.ready) {
    onBypass();
    return null;
  }

  const completedSteps = [
    readiness.repo_connected ? "connect_repo" : null,
    readiness.repo_indexed ? "index_repo" : null,
    readiness.db_connected ? "connect_db" : null,
    readiness.db_indexed ? "index_db" : null,
    readiness.code_db_synced ? "sync" : null,
  ];
  const allSteps = ["connect_repo", "index_repo", "connect_db", "index_db", "sync"];
  const actionableSteps = new Set(["index_repo", "index_db", "sync"]);

  const handleNavigate = (step: string) => {
    const nav = NAVIGABLE_STEPS[step];
    if (!nav) return;
    const store = useAppStore.getState();
    store.setFocusSidebarSection(nav.section);
    if (nav.editProject) {
      store.setTriggerProjectEdit(true);
    }
  };

  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="max-w-md w-full mx-4 bg-zinc-800/50 border border-zinc-700 rounded-xl p-6 space-y-4">
        <h3 className="text-sm font-medium text-zinc-200">
          Set up your project for full AI queries
        </h3>

        <div className="space-y-2">
          {allSteps.map((step, idx) => {
            const done = completedSteps.includes(step);
            const canAct = actionableSteps.has(step) && !done;
            const prevStepDone = idx === 0 || completedSteps.includes(allSteps[idx - 1]);
            const isRunning = actionInProgress === step;
            const isNavigable = !done && step in NAVIGABLE_STEPS;

            return (
              <div key={step} className="flex items-center gap-3">
                <span className="text-base w-5 text-center">
                  {done ? (
                    <span className="text-green-400">✓</span>
                  ) : (
                    <span className="text-zinc-600">{idx + 1}</span>
                  )}
                </span>
                {isNavigable ? (
                  <button
                    onClick={() => handleNavigate(step)}
                    className="flex-1 text-sm text-left text-blue-400 hover:text-blue-300 hover:underline cursor-pointer transition-colors"
                  >
                    {STEP_LABELS[step] || step}
                    <span className="ml-1.5 text-[10px] opacity-60">→</span>
                  </button>
                ) : (
                  <span className={`flex-1 text-sm ${done ? "text-zinc-400 line-through" : "text-zinc-300"}`}>
                    {STEP_LABELS[step] || step}
                  </span>
                )}
                {canAct && prevStepDone && (
                  <button
                    onClick={() => handleAction(step)}
                    disabled={isRunning}
                    className="text-[10px] px-2 py-1 rounded bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50"
                  >
                    {isRunning ? "Running..." : "Run"}
                  </button>
                )}
              </div>
            );
          })}
        </div>

        <div className="border-t border-zinc-700 pt-3 space-y-2">
          <p className="text-xs text-amber-400/80">
            You can still chat, but SQL queries may be less accurate without sync.
          </p>
          <button
            onClick={() => {
              useLogStore.getState().setOpen(false);
              onBypass();
            }}
            className="w-full text-sm px-4 py-2 rounded-lg bg-zinc-700 text-zinc-300 hover:bg-zinc-600 transition-colors"
          >
            Chat anyway
          </button>
        </div>
      </div>
    </div>
  );
}

export function ReadinessBanner({ projectId }: { projectId: string }) {
  const [missing, setMissing] = useState<string[]>([]);
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
    }).catch(() => {});
  }, [projectId]);

  if (missing.length === 0) return null;

  return (
    <div className="flex items-center px-6 py-1.5 bg-amber-900/20 border-b border-amber-800/30 text-xs text-amber-400">
      <span>Missing: {missing.join(" → ")}</span>
    </div>
  );
}
