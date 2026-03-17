"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Project, type RepoCheckResult } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { InviteManager } from "./InviteManager";
import { confirmAction } from "@/components/ui/ConfirmModal";
import { toast } from "@/stores/toast-store";
import { Spinner } from "@/components/ui/Spinner";
import {
  LlmModelSelector,
  formatProvider,
  formatModelShort,
  EMPTY_LLM,
  type LlmPair,
} from "@/components/ui/LlmModelSelector";

const inputCls =
  "w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-1.5 text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-blue-500";

function isSshUrl(url: string): boolean {
  const trimmed = url.trim();
  return trimmed.startsWith("git@") || trimmed.startsWith("ssh://");
}

interface ProjectFormState {
  name: string;
  repoUrl: string;
  branch: string;
  sshKeyId: string;
  indexing: LlmPair;
  agent: LlmPair;
  sql: LlmPair;
  sqlSameAsAgent: boolean;
}

const EMPTY_FORM: ProjectFormState = {
  name: "",
  repoUrl: "",
  branch: "main",
  sshKeyId: "",
  indexing: { ...EMPTY_LLM },
  agent: { ...EMPTY_LLM },
  sql: { ...EMPTY_LLM },
  sqlSameAsAgent: true,
};

function sqlMatchesAgent(sql: LlmPair, agent: LlmPair): boolean {
  return sql.provider === agent.provider && sql.model === agent.model;
}

function projectToForm(p: Project): ProjectFormState {
  const agent: LlmPair = {
    provider: p.agent_llm_provider || "",
    model: p.agent_llm_model || "",
  };
  const sql: LlmPair = {
    provider: p.sql_llm_provider || "",
    model: p.sql_llm_model || "",
  };
  return {
    name: p.name,
    repoUrl: p.repo_url || "",
    branch: p.repo_branch || "main",
    sshKeyId: p.ssh_key_id || "",
    indexing: {
      provider: p.indexing_llm_provider || "",
      model: p.indexing_llm_model || "",
    },
    agent,
    sql,
    sqlSameAsAgent: sqlMatchesAgent(sql, agent),
  };
}

function LlmBadges({ project }: { project: Project }) {
  const lines: { label: string; text: string }[] = [];
  if (project.indexing_llm_provider) {
    lines.push({
      label: "Idx",
      text: `${formatProvider(project.indexing_llm_provider)}${project.indexing_llm_model ? " / " + formatModelShort(project.indexing_llm_model) : ""}`,
    });
  }
  if (project.agent_llm_provider) {
    lines.push({
      label: "Agent",
      text: `${formatProvider(project.agent_llm_provider)}${project.agent_llm_model ? " / " + formatModelShort(project.agent_llm_model) : ""}`,
    });
  }
  if (project.sql_llm_provider) {
    const isSameAsAgent =
      project.sql_llm_provider === project.agent_llm_provider &&
      project.sql_llm_model === project.agent_llm_model;
    if (!isSameAsAgent) {
      lines.push({
        label: "SQL",
        text: `${formatProvider(project.sql_llm_provider)}${project.sql_llm_model ? " / " + formatModelShort(project.sql_llm_model) : ""}`,
      });
    }
  }
  if (lines.length === 0) {
    return (
      <span className="block text-[10px] text-zinc-600 italic">
        System defaults
      </span>
    );
  }
  return (
    <span className="block space-y-0">
      {lines.map((l) => (
        <span key={l.label} className="block text-[10px] text-zinc-500 leading-tight">
          <span className="text-zinc-600">{l.label}:</span> {l.text}
        </span>
      ))}
    </span>
  );
}

export function ProjectSelector() {
  const {
    sshKeys,
    projects,
    activeProject,
    setProjects,
    setActiveProject,
    setConnections,
    setActiveConnection,
    clearMessages,
    setChatSessions,
    setActiveSession,
  } = useAppStore();
  const setUserRole = useAppStore((s) => s.setUserRole);
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [managingAccessId, setManagingAccessId] = useState<string | null>(null);
  const [form, setForm] = useState<ProjectFormState>({ ...EMPTY_FORM });
  const [checking, setChecking] = useState(false);
  const [accessResult, setAccessResult] = useState<RepoCheckResult | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [listLoading, setListLoading] = useState(true);

  useEffect(() => {
    api.projects.list().then(setProjects).catch((err) => {
      toast(err instanceof Error ? err.message : "Failed to load projects", "error");
    }).finally(() => setListLoading(false));
  }, [setProjects]);

  const runAccessCheck = useCallback(
    async (repoUrl: string, sshKeyId: string) => {
      if (!repoUrl.trim()) return;
      setChecking(true);
      setAccessResult(null);
      try {
        const result = await api.repos.checkAccess({
          repo_url: repoUrl.trim(),
          ssh_key_id: sshKeyId || null,
        });
        setAccessResult(result);
        if (result.accessible && result.default_branch) {
          setForm((prev) => ({ ...prev, branch: result.default_branch! }));
        }
      } catch {
        setAccessResult({
          accessible: false,
          branches: [],
          default_branch: null,
          error: "Failed to check access",
        });
      } finally {
        setChecking(false);
      }
    },
    [],
  );

  useEffect(() => {
    const url = form.repoUrl.trim();
    if (!url) {
      setAccessResult(null);
      return;
    }
    if (isSshUrl(url) && !form.sshKeyId) return;

    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(
      () => runAccessCheck(url, form.sshKeyId),
      800,
    );
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [form.repoUrl, form.sshKeyId, runAccessCheck]);

  useEffect(() => {
    const url = form.repoUrl.trim();
    if (!url || !isSshUrl(url) || form.sshKeyId) return;
    if (sshKeys.length === 1) {
      setForm((prev) => ({ ...prev, sshKeyId: sshKeys[0].id }));
    }
  }, [form.repoUrl, form.sshKeyId, sshKeys]);

  const resetForm = () => {
    setForm({ ...EMPTY_FORM });
    setAccessResult(null);
    setChecking(false);
  };

  const [nameError, setNameError] = useState("");

  const resolveSql = (): LlmPair =>
    form.sqlSameAsAgent ? form.agent : form.sql;

  const handleCreate = async () => {
    if (!form.name.trim()) {
      setNameError("Name is required");
      return;
    }
    setNameError("");
    const sql = resolveSql();
    try {
      const project = await api.projects.create({
        name: form.name.trim(),
        repo_url: form.repoUrl.trim() || null,
        repo_branch: form.branch.trim() || "main",
        ssh_key_id: form.sshKeyId || null,
        indexing_llm_provider: form.indexing.provider || null,
        indexing_llm_model: form.indexing.model || null,
        agent_llm_provider: form.agent.provider || null,
        agent_llm_model: form.agent.model || null,
        sql_llm_provider: sql.provider || null,
        sql_llm_model: sql.model || null,
      });
      useAppStore.setState((state) => ({
        projects: [project, ...state.projects],
      }));
      setActiveProject(project);
      resetForm();
      setShowCreate(false);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to create project", "error");
    }
  };

  const handleEdit = (p: Project) => {
    setEditingId(p.id);
    setForm(projectToForm(p));
    setShowCreate(false);
    setAccessResult(null);
    setChecking(false);
    setNameError("");
  };

  const handleUpdate = async () => {
    if (!editingId) return;
    if (!form.name.trim()) {
      setNameError("Name is required");
      return;
    }
    setNameError("");
    const sql = resolveSql();
    try {
      const updated = await api.projects.update(editingId, {
        name: form.name.trim(),
        repo_url: form.repoUrl.trim() || null,
        repo_branch: form.branch.trim() || "main",
        ssh_key_id: form.sshKeyId || null,
        indexing_llm_provider: form.indexing.provider || null,
        indexing_llm_model: form.indexing.model || null,
        agent_llm_provider: form.agent.provider || null,
        agent_llm_model: form.agent.model || null,
        sql_llm_provider: sql.provider || null,
        sql_llm_model: sql.model || null,
      });
      useAppStore.setState((state) => ({
        projects: state.projects.map((p) => (p.id === updated.id ? updated : p)),
        ...(state.activeProject?.id === updated.id ? { activeProject: updated } : {}),
      }));
      setEditingId(null);
      resetForm();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to update project", "error");
    }
  };

  const handleSelect = async (project: Project) => {
    setActiveProject(project);
    setUserRole(project.user_role || null);
    clearMessages();
    setActiveSession(null);
    setChatSessions([]);
    setConnections([]);
    setActiveConnection(null);
    try {
      const [conns, sessions] = await Promise.all([
        api.connections.listByProject(project.id),
        api.chat.listSessions(project.id),
      ]);
      setConnections(conns);
      setActiveConnection(conns[0] || null);
      setChatSessions(sessions);
    } catch {
      setConnections([]);
      setActiveConnection(null);
      setChatSessions([]);
    }
  };

  const handleDelete = async (e: React.MouseEvent, project: Project) => {
    e.stopPropagation();
    if (!(await confirmAction(`Delete project "${project.name}"?`))) return;
    try {
      await api.projects.delete(project.id);
      useAppStore.setState((state) => ({
        projects: state.projects.filter((p) => p.id !== project.id),
        ...(state.activeProject?.id === project.id
          ? {
              activeProject: null,
              connections: [],
              activeConnection: null,
              chatSessions: [],
              activeSession: null,
              messages: [],
            }
          : {}),
      }));
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to delete project", "error");
    }
  };

  const isFormOpen = showCreate || editingId !== null;

  const formUI = (
    <div className="space-y-2 p-2 bg-zinc-800/50 rounded-lg">
      <div>
        <input
          value={form.name}
          onChange={(e) => { setForm({ ...form, name: e.target.value }); setNameError(""); }}
          placeholder="Project name"
          className={`${inputCls} ${nameError ? "border-red-500" : ""}`}
        />
        {nameError && <p className="text-[10px] text-red-400 mt-0.5 px-1">{nameError}</p>}
      </div>
      <div className="space-y-1">
        <input
          value={form.repoUrl}
          onChange={(e) => setForm({ ...form, repoUrl: e.target.value })}
          placeholder="Git repo URL (optional)"
          className={inputCls}
        />
        {form.repoUrl.trim() && (
          <div className="flex items-center gap-1.5 px-1 min-h-[18px]">
            {checking && (
              <span className="text-[10px] text-zinc-500 animate-pulse">Checking access...</span>
            )}
            {!checking && accessResult?.accessible && (
              <span className="text-[10px] text-emerald-400">
                ✓ Access verified
                {accessResult.branches.length > 0 && (
                  <span className="text-zinc-500 ml-1">
                    ({accessResult.branches.length} branch{accessResult.branches.length !== 1 ? "es" : ""})
                  </span>
                )}
              </span>
            )}
            {!checking && accessResult && !accessResult.accessible && (
              <span className="text-[10px] text-red-400" title={accessResult.error || undefined}>
                ✕ {accessResult.error || "Access denied"}
              </span>
            )}
            {!checking && !accessResult && isSshUrl(form.repoUrl) && !form.sshKeyId && sshKeys.length === 0 && (
              <span className="text-[10px] text-amber-400">SSH URL detected — add an SSH key first</span>
            )}
            {!checking && !accessResult && isSshUrl(form.repoUrl) && !form.sshKeyId && sshKeys.length > 1 && (
              <span className="text-[10px] text-amber-400">Select an SSH key to verify access</span>
            )}
          </div>
        )}
      </div>
      {form.repoUrl.trim() && (
        <>
          <select
            value={form.sshKeyId}
            onChange={(e) => setForm({ ...form, sshKeyId: e.target.value })}
            className={inputCls}
          >
            <option value="">SSH Key (none)</option>
            {sshKeys.map((k) => (
              <option key={k.id} value={k.id}>
                {k.name} ({k.key_type})
              </option>
            ))}
          </select>
          {accessResult?.accessible && accessResult.branches.length > 0 ? (
            <select
              value={form.branch}
              onChange={(e) => setForm({ ...form, branch: e.target.value })}
              className={inputCls}
            >
              {accessResult.branches.map((b) => (
                <option key={b} value={b}>{b}</option>
              ))}
            </select>
          ) : (
            <input
              value={form.branch}
              onChange={(e) => setForm({ ...form, branch: e.target.value })}
              placeholder="Branch (default: main)"
              className={inputCls}
            />
          )}
        </>
      )}
      <details open={!!editingId} className="group/llm">
        <summary className="flex items-center gap-1.5 cursor-pointer select-none py-1 text-[11px] font-medium text-zinc-300 hover:text-zinc-100 transition-colors">
          <svg
            className="w-3 h-3 text-zinc-500 transition-transform group-open/llm:rotate-90"
            viewBox="0 0 16 16"
            fill="currentColor"
          >
            <path d="M6 3l5 5-5 5V3z" />
          </svg>
          LLM Models
        </summary>
        <div className="space-y-3 pt-1.5 pl-0.5">
          <LlmModelSelector
            label="Indexing"
            description="Repo analysis & docs"
            pair={form.indexing}
            onChange={(p) => setForm({ ...form, indexing: p })}
          />
          <LlmModelSelector
            label="Agent"
            description="Chat & reasoning"
            pair={form.agent}
            onChange={(p) => {
              const next: Partial<ProjectFormState> = { agent: p };
              if (form.sqlSameAsAgent) {
                next.sql = { ...p };
              }
              setForm({ ...form, ...next });
            }}
          />
          <div className="space-y-1">
            <LlmModelSelector
              label="SQL"
              description="Query generation & repair"
              pair={form.sqlSameAsAgent ? form.agent : form.sql}
              onChange={(p) => setForm({ ...form, sql: p })}
              disabled={form.sqlSameAsAgent}
            />
            <label className="flex items-center gap-1.5 cursor-pointer pl-0.5">
              <input
                type="checkbox"
                checked={form.sqlSameAsAgent}
                onChange={(e) => {
                  const checked = e.target.checked;
                  setForm({
                    ...form,
                    sqlSameAsAgent: checked,
                    sql: checked ? { ...form.agent } : form.sql,
                  });
                }}
                className="w-3 h-3 rounded border-zinc-600 bg-zinc-900 text-blue-500 focus:ring-1 focus:ring-blue-500 focus:ring-offset-0"
              />
              <span className="text-[10px] text-zinc-500">
                Use Agent model
              </span>
            </label>
          </div>
        </div>
      </details>
      <div className="flex gap-2">
        <button
          onClick={editingId ? handleUpdate : handleCreate}
          className="flex-1 px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-500"
        >
          {editingId ? "Save Changes" : "Create"}
        </button>
        {editingId && (
          <button
            onClick={() => { setEditingId(null); resetForm(); }}
            className="px-3 py-1.5 text-zinc-400 hover:text-zinc-200 text-xs"
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <button
          onClick={() => {
            if (showCreate) {
              setShowCreate(false);
              resetForm();
            } else {
              setEditingId(null);
              resetForm();
              setShowCreate(true);
            }
          }}
          className="text-xs text-blue-400 hover:text-blue-300"
        >
          {showCreate ? "Cancel" : "+ New"}
        </button>
      </div>

      {isFormOpen && formUI}

      {listLoading && <Spinner />}
      <div className="space-y-1">
        {projects.map((p) => (
          <div key={p.id} className="flex items-center group">
            <button
              onClick={() => handleSelect(p)}
              className={`flex-1 text-left px-3 py-2 rounded-md text-sm transition-colors ${
                activeProject?.id === p.id
                  ? "bg-zinc-800 text-zinc-100"
                  : "text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-300"
              }`}
            >
              <span className="flex items-center gap-1.5">
                {p.name}
                {p.user_role && (
                  <span className={`px-1 py-0.5 rounded text-[9px] font-medium leading-none ${
                    p.user_role === "owner"
                      ? "bg-amber-500/20 text-amber-300"
                      : p.user_role === "editor"
                        ? "bg-blue-500/20 text-blue-300"
                        : "bg-zinc-500/20 text-zinc-400"
                  }`}>
                    {p.user_role}
                  </span>
                )}
              </span>
              {activeProject?.id === p.id && (
                <LlmBadges project={p} />
              )}
            </button>
            {p.user_role === "owner" && (
              <button
                onClick={(e) => { e.stopPropagation(); setManagingAccessId(managingAccessId === p.id ? null : p.id); }}
                className="text-[10px] text-zinc-600 hover:text-green-400 px-1 opacity-0 group-hover:opacity-100 transition-opacity"
                title="Manage access"
              >
                👥
              </button>
            )}
            {p.user_role === "owner" && (
              <button
                onClick={() => handleEdit(p)}
                className="text-[10px] text-zinc-600 hover:text-blue-400 px-1 opacity-0 group-hover:opacity-100 transition-opacity"
                title="Edit project"
              >
                ✎
              </button>
            )}
            {p.user_role === "owner" && (
              <button
                onClick={(e) => handleDelete(e, p)}
                className="text-xs text-zinc-600 hover:text-red-400 px-1 opacity-0 group-hover:opacity-100 transition-opacity"
                title="Delete project"
              >
                ×
              </button>
            )}
          </div>
        ))}
      </div>

      {managingAccessId && (
        <InviteManager
          projectId={managingAccessId}
          onClose={() => setManagingAccessId(null)}
        />
      )}
    </div>
  );
}
