"use client";

import { SshKeyManager } from "./ssh/SshKeyManager";
import { ProjectSelector } from "./projects/ProjectSelector";
import { ConnectionSelector } from "./connections/ConnectionSelector";
import { ChatSessionList } from "./chat/ChatSessionList";
import { RulesManager } from "./rules/RulesManager";
import { KnowledgeDocs } from "./knowledge/KnowledgeDocs";
import { WorkflowProgress } from "./workflow/WorkflowProgress";
import { PendingInvites } from "./invites/PendingInvites";
import { useAppStore } from "@/stores/app-store";
import { api } from "@/lib/api";
import type { RepoStatus, UpdateCheck } from "@/lib/api";
import { useState, useEffect, useCallback } from "react";

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

export function Sidebar() {
  const { activeProject } = useAppStore();
  const [indexing, setIndexing] = useState(false);
  const [indexResult, setIndexResult] = useState<string | null>(null);
  const [indexWorkflowId, setIndexWorkflowId] = useState<string | null>(null);
  const [repoStatus, setRepoStatus] = useState<RepoStatus | null>(null);
  const [updateCheck, setUpdateCheck] = useState<UpdateCheck | null>(null);
  const [checking, setChecking] = useState(false);

  const loadStatus = useCallback(async () => {
    if (!activeProject?.repo_url) {
      setRepoStatus(null);
      return;
    }
    try {
      const st = await api.repos.status(activeProject.id);
      setRepoStatus(st);
    } catch {
      setRepoStatus(null);
    }
  }, [activeProject]);

  useEffect(() => {
    setRepoStatus(null);
    setUpdateCheck(null);
    setIndexResult(null);
    loadStatus();
  }, [activeProject?.id, loadStatus]);

  const handleIndex = async () => {
    if (!activeProject) return;
    setIndexing(true);
    setIndexResult(null);
    setIndexWorkflowId(null);
    setUpdateCheck(null);
    try {
      const result = await api.repos.index(activeProject.id);
      setIndexWorkflowId(result.workflow_id);
      setIndexResult(`Indexed ${result.files_indexed} files, found ${result.schemas_found} schemas`);
      await loadStatus();
    } catch (err) {
      setIndexResult(`Error: ${err instanceof Error ? err.message : "Unknown"}`);
    } finally {
      setIndexing(false);
    }
  };

  const handleCheckUpdates = async () => {
    if (!activeProject) return;
    setChecking(true);
    setUpdateCheck(null);
    try {
      const uc = await api.repos.checkUpdates(activeProject.id);
      setUpdateCheck(uc);
    } catch {
      setUpdateCheck({ has_updates: false, commits_behind: 0, message: "Check failed" });
    } finally {
      setChecking(false);
    }
  };

  return (
    <aside className="w-72 border-r border-zinc-800 flex flex-col h-full">
      <div className="p-4 border-b border-zinc-800">
        <h1 className="text-lg font-semibold text-zinc-100">DB Agent</h1>
        <p className="text-xs text-zinc-500 mt-0.5">AI Database Query Assistant</p>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        <PendingInvites />
        <SshKeyManager />
        <ProjectSelector />
        <ConnectionSelector />
        <ChatSessionList />
        <RulesManager />
        <KnowledgeDocs />

        {activeProject?.repo_url && (
          <div className="space-y-2">
            <h3 className="text-xs font-medium text-zinc-500 uppercase tracking-wider">
              Repository
            </h3>

            {repoStatus && (
              <div className="text-xs text-zinc-400 space-y-1 bg-zinc-900 rounded-md p-2">
                {repoStatus.last_indexed_commit ? (
                  <>
                    <div className="flex justify-between">
                      <span>Last indexed:</span>
                      <span className="text-zinc-300 font-mono">
                        {repoStatus.last_indexed_commit.slice(0, 7)}
                      </span>
                    </div>
                    {repoStatus.last_indexed_at && (
                      <div className="flex justify-between">
                        <span>When:</span>
                        <span className="text-zinc-300">
                          {timeAgo(repoStatus.last_indexed_at)}
                        </span>
                      </div>
                    )}
                    <div className="flex justify-between">
                      <span>Branch:</span>
                      <span className="text-zinc-300">{repoStatus.branch}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Documents:</span>
                      <span className="text-zinc-300">{repoStatus.total_documents}</span>
                    </div>
                  </>
                ) : (
                  <p className="text-zinc-500 italic">Not yet indexed</p>
                )}
                {repoStatus.is_indexing && (
                  <p className="text-amber-400 text-xs mt-1">Indexing in progress...</p>
                )}
              </div>
            )}

            <div className="flex gap-1">
              <button
                onClick={handleIndex}
                disabled={indexing}
                className="flex-1 px-3 py-2 text-xs bg-zinc-800 text-zinc-300 rounded-md hover:bg-zinc-700 disabled:opacity-50 transition-colors"
              >
                {indexing ? "Indexing..." : "Index Repository"}
              </button>
              {repoStatus?.last_indexed_commit && (
                <button
                  onClick={handleCheckUpdates}
                  disabled={checking || indexing}
                  title="Check for new commits"
                  className="px-2 py-2 text-xs bg-zinc-800 text-zinc-400 rounded-md hover:bg-zinc-700 disabled:opacity-50 transition-colors"
                >
                  {checking ? "..." : "Check"}
                </button>
              )}
            </div>

            {updateCheck && (
              <p className={`text-xs ${updateCheck.has_updates ? "text-amber-400" : "text-green-400"}`}>
                {updateCheck.message}
                {updateCheck.has_updates && updateCheck.commits_behind > 0 && (
                  <button
                    onClick={handleIndex}
                    disabled={indexing}
                    className="ml-1 underline hover:text-amber-300"
                  >
                    Re-index now
                  </button>
                )}
              </p>
            )}

            {indexing && indexWorkflowId && (
              <WorkflowProgress workflowId={indexWorkflowId} />
            )}
            {!indexing && indexWorkflowId && (
              <WorkflowProgress workflowId={indexWorkflowId} />
            )}
            {indexResult && (
              <p className={`text-xs ${indexResult.startsWith("Error") ? "text-red-400" : "text-green-400"}`}>
                {indexResult}
              </p>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
