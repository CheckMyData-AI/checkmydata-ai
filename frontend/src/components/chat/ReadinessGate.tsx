"use client";

import { useEffect, useState, useCallback } from "react";
import { api, type ProjectReadiness } from "@/lib/api";
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

export function ReadinessGate({ projectId, connectionId, onBypass }: ReadinessGateProps) {
  const [readiness, setReadiness] = useState<ProjectReadiness | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);

  const fetchReadiness = useCallback(async () => {
    try {
      const r = await api.projects.readiness(projectId);
      setReadiness(r);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    fetchReadiness();
  }, [fetchReadiness, connectionId]);

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
      setTimeout(fetchReadiness, 3000);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Action failed", "error");
    } finally {
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

  if (!readiness || readiness.ready) return null;

  const completedSteps = [
    readiness.repo_connected ? "connect_repo" : null,
    readiness.repo_indexed ? "index_repo" : null,
    readiness.db_connected ? "connect_db" : null,
    readiness.db_indexed ? "index_db" : null,
    readiness.code_db_synced ? "sync" : null,
  ];
  const allSteps = ["connect_repo", "index_repo", "connect_db", "index_db", "sync"];
  const actionableSteps = new Set(["index_repo", "index_db", "sync"]);

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

            return (
              <div key={step} className="flex items-center gap-3">
                <span className="text-base w-5 text-center">
                  {done ? (
                    <span className="text-green-400">✓</span>
                  ) : (
                    <span className="text-zinc-600">{idx + 1}</span>
                  )}
                </span>
                <span className={`flex-1 text-sm ${done ? "text-zinc-400 line-through" : "text-zinc-300"}`}>
                  {STEP_LABELS[step] || step}
                </span>
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
            onClick={onBypass}
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

  useEffect(() => {
    api.projects.readiness(projectId).then((r) => {
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
