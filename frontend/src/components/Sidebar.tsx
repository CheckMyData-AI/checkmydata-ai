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

function getCollapsed(): Record<string, boolean> {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(localStorage.getItem("sidebar_collapsed") || "{}");
  } catch {
    return {};
  }
}

function useSectionCollapse(id: string, defaultOpen = true) {
  const [open, setOpen] = useState(() => {
    const saved = getCollapsed();
    return saved[id] !== undefined ? !saved[id] : defaultOpen;
  });

  const toggle = () => {
    setOpen((prev) => {
      const next = !prev;
      const saved = getCollapsed();
      saved[id] = !next;
      localStorage.setItem("sidebar_collapsed", JSON.stringify(saved));
      return next;
    });
  };

  return { open, toggle };
}

function SectionToggle({ open, toggle }: { open: boolean; toggle: () => void }) {
  return (
    <button
      onClick={toggle}
      className="text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors px-1"
      title={open ? "Collapse" : "Expand"}
    >
      {open ? "▾" : "▸"}
    </button>
  );
}

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
    } catch (err) {
      setIndexResult(`Error: ${err instanceof Error ? err.message : "Unknown"}`);
      setIndexing(false);
    }
  };

  const handleIndexComplete = useCallback(
    (status: "completed" | "failed", detail: string) => {
      setIndexing(false);
      if (status === "completed") {
        setIndexResult(detail || "Indexing completed");
      } else {
        setIndexResult(`Error: ${detail || "Indexing failed"}`);
      }
      loadStatus();
    },
    [loadStatus],
  );

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

  const { sshKeys, projects, connections } = useAppStore();
  const showOnboarding = projects.length === 0;

  const sshCollapse = useSectionCollapse("ssh-keys");
  const projectsCollapse = useSectionCollapse("projects");
  const repoCollapse = useSectionCollapse("repository");
  const connCollapse = useSectionCollapse("connections");
  const chatCollapse = useSectionCollapse("chat-history");
  const rulesCollapse = useSectionCollapse("rules", false);
  const knowledgeCollapse = useSectionCollapse("knowledge", false);

  const repoSection = activeProject?.repo_url ? (
    <div className="space-y-2">
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

      {indexWorkflowId && (
        <WorkflowProgress workflowId={indexWorkflowId} onComplete={handleIndexComplete} />
      )}
      {indexResult && (
        <p className={`text-xs ${indexResult.startsWith("Error") ? "text-red-400" : "text-green-400"}`}>
          {indexResult}
        </p>
      )}
    </div>
  ) : null;

  return (
    <aside className="w-72 border-r border-zinc-800 flex flex-col h-full">
      <div className="p-4 border-b border-zinc-800">
        <h1 className="text-lg font-semibold text-zinc-100">DB Agent</h1>
        <p className="text-xs text-zinc-500 mt-0.5">AI Database Query Assistant</p>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        <PendingInvites />

        {showOnboarding && (
          <div className="p-3 bg-blue-500/10 border border-blue-500/20 rounded-lg space-y-2">
            <p className="text-xs font-medium text-blue-300">Getting Started</p>
            <div className="space-y-1.5 text-[11px] text-zinc-400">
              <div className="flex items-center gap-2">
                <span className={`w-4 h-4 rounded-full flex items-center justify-center text-[9px] ${sshKeys.length > 0 ? "bg-emerald-900/50 text-emerald-400" : "bg-zinc-800 text-zinc-500"}`}>
                  {sshKeys.length > 0 ? "✓" : "1"}
                </span>
                <span className={sshKeys.length > 0 ? "text-zinc-500 line-through" : ""}>
                  Add an SSH key
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className={`w-4 h-4 rounded-full flex items-center justify-center text-[9px] ${projects.length > 0 ? "bg-emerald-900/50 text-emerald-400" : "bg-zinc-800 text-zinc-500"}`}>
                  {projects.length > 0 ? "✓" : "2"}
                </span>
                <span className={projects.length > 0 ? "text-zinc-500 line-through" : ""}>
                  Create your first project
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className={`w-4 h-4 rounded-full flex items-center justify-center text-[9px] ${connections.length > 0 ? "bg-emerald-900/50 text-emerald-400" : "bg-zinc-800 text-zinc-500"}`}>
                  {connections.length > 0 ? "✓" : "3"}
                </span>
                <span className={connections.length > 0 ? "text-zinc-500 line-through" : ""}>
                  Add a database connection
                </span>
              </div>
            </div>
          </div>
        )}

        <div>
          <div className="flex items-center justify-between mb-1">
            <SectionToggle {...sshCollapse} />
            <h3 className="flex-1 text-xs font-medium text-zinc-500 uppercase tracking-wider cursor-pointer" onClick={sshCollapse.toggle}>SSH Keys</h3>
          </div>
          {sshCollapse.open && <SshKeyManager />}
        </div>

        <div>
          <div className="flex items-center justify-between mb-1">
            <SectionToggle {...projectsCollapse} />
            <h3 className="flex-1 text-xs font-medium text-zinc-500 uppercase tracking-wider cursor-pointer" onClick={projectsCollapse.toggle}>Projects</h3>
          </div>
          {projectsCollapse.open && <ProjectSelector />}
        </div>

        {activeProject && (
          <>
            {activeProject.repo_url && (
              <div>
                <div className="flex items-center justify-between mb-1">
                  <SectionToggle {...repoCollapse} />
                  <h3 className="flex-1 text-xs font-medium text-zinc-500 uppercase tracking-wider cursor-pointer" onClick={repoCollapse.toggle}>Repository</h3>
                </div>
                {repoCollapse.open && repoSection}
              </div>
            )}

            <div>
              <div className="flex items-center justify-between mb-1">
                <SectionToggle {...connCollapse} />
                <h3 className="flex-1 text-xs font-medium text-zinc-500 uppercase tracking-wider cursor-pointer" onClick={connCollapse.toggle}>Connections</h3>
              </div>
              {connCollapse.open && <ConnectionSelector />}
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <SectionToggle {...chatCollapse} />
                <h3 className="flex-1 text-xs font-medium text-zinc-500 uppercase tracking-wider cursor-pointer" onClick={chatCollapse.toggle}>Chat History</h3>
              </div>
              {chatCollapse.open && <ChatSessionList />}
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <SectionToggle {...rulesCollapse} />
                <h3 className="flex-1 text-xs font-medium text-zinc-500 uppercase tracking-wider cursor-pointer" onClick={rulesCollapse.toggle}>Custom Rules</h3>
              </div>
              {rulesCollapse.open && <RulesManager />}
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <SectionToggle {...knowledgeCollapse} />
                <h3 className="flex-1 text-xs font-medium text-zinc-500 uppercase tracking-wider cursor-pointer" onClick={knowledgeCollapse.toggle}>Knowledge</h3>
              </div>
              {knowledgeCollapse.open && <KnowledgeDocs />}
            </div>
          </>
        )}
      </div>
    </aside>
  );
}
