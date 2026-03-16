"use client";

import { useEffect, useState } from "react";
import { api, type Project } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { InviteManager } from "./InviteManager";

const LLM_PROVIDERS = ["openai", "anthropic", "openrouter"];

const inputCls =
  "w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-1.5 text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-blue-500";

interface ProjectFormState {
  name: string;
  repoUrl: string;
  branch: string;
  sshKeyId: string;
  llmProvider: string;
  llmModel: string;
}

const EMPTY_FORM: ProjectFormState = {
  name: "",
  repoUrl: "",
  branch: "main",
  sshKeyId: "",
  llmProvider: "",
  llmModel: "",
};

function projectToForm(p: Project): ProjectFormState {
  return {
    name: p.name,
    repoUrl: p.repo_url || "",
    branch: p.repo_branch || "main",
    sshKeyId: p.ssh_key_id || "",
    llmProvider: p.default_llm_provider || "",
    llmModel: p.default_llm_model || "",
  };
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

  useEffect(() => {
    api.projects.list().then(setProjects).catch(console.error);
  }, [setProjects]);

  const resetForm = () => setForm({ ...EMPTY_FORM });

  const handleCreate = async () => {
    if (!form.name.trim()) return;
    const project = await api.projects.create({
      name: form.name.trim(),
      repo_url: form.repoUrl.trim() || null,
      repo_branch: form.branch.trim() || "main",
      ssh_key_id: form.sshKeyId || null,
      default_llm_provider: form.llmProvider || null,
      default_llm_model: form.llmModel || null,
    });
    useAppStore.setState((state) => ({
      projects: [project, ...state.projects],
    }));
    setActiveProject(project);
    resetForm();
    setShowCreate(false);
  };

  const handleEdit = (p: Project) => {
    setEditingId(p.id);
    setForm(projectToForm(p));
    setShowCreate(false);
  };

  const handleUpdate = async () => {
    if (!editingId || !form.name.trim()) return;
    const updated = await api.projects.update(editingId, {
      name: form.name.trim(),
      repo_url: form.repoUrl.trim() || null,
      repo_branch: form.branch.trim() || "main",
      ssh_key_id: form.sshKeyId || null,
      default_llm_provider: form.llmProvider || null,
      default_llm_model: form.llmModel || null,
    });
    useAppStore.setState((state) => ({
      projects: state.projects.map((p) => (p.id === updated.id ? updated : p)),
      ...(state.activeProject?.id === updated.id ? { activeProject: updated } : {}),
    }));
    setEditingId(null);
    resetForm();
  };

  const handleSelect = async (project: Project) => {
    setActiveProject(project);
    setUserRole(project.user_role || null);
    clearMessages();
    setActiveSession(null);
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
    if (!confirm(`Delete project "${project.name}"?`)) return;
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
      console.error("Failed to delete project", err);
    }
  };

  const isFormOpen = showCreate || editingId !== null;

  const formUI = (
    <div className="space-y-2 p-2 bg-zinc-800/50 rounded-lg">
      <input
        value={form.name}
        onChange={(e) => setForm({ ...form, name: e.target.value })}
        placeholder="Project name"
        className={inputCls}
      />
      <input
        value={form.repoUrl}
        onChange={(e) => setForm({ ...form, repoUrl: e.target.value })}
        placeholder="Git repo URL (optional)"
        className={inputCls}
      />
      {form.repoUrl.trim() && (
        <>
          <input
            value={form.branch}
            onChange={(e) => setForm({ ...form, branch: e.target.value })}
            placeholder="Branch (default: main)"
            className={inputCls}
          />
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
        </>
      )}
      <div className="grid grid-cols-2 gap-2">
        <select
          value={form.llmProvider}
          onChange={(e) => setForm({ ...form, llmProvider: e.target.value })}
          className={inputCls}
        >
          <option value="">LLM Provider (default)</option>
          {LLM_PROVIDERS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <input
          value={form.llmModel}
          onChange={(e) => setForm({ ...form, llmModel: e.target.value })}
          placeholder="Model (e.g. gpt-4o)"
          className={inputCls}
        />
      </div>
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
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-zinc-500 uppercase tracking-wider">
          Projects
        </h3>
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
              {activeProject?.id === p.id && p.default_llm_provider && (
                <span className="block text-[10px] text-zinc-500">
                  {p.default_llm_provider}
                  {p.default_llm_model ? ` / ${p.default_llm_model}` : ""}
                </span>
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
