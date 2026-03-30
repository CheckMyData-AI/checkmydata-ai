"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Project, type RepoCheckResult } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { useAuthStore } from "@/stores/auth-store";
import { InviteManager } from "./InviteManager";
import { RequestAccessModal } from "./RequestAccessModal";
import { confirmAction } from "@/components/ui/ConfirmModal";
import { toast } from "@/stores/toast-store";
import { invalidateRestore } from "@/hooks/useRestoreState";
import { Spinner } from "@/components/ui/Spinner";
import { Icon } from "@/components/ui/Icon";
import { ActionButton } from "@/components/ui/ActionButton";
import { FormModal } from "@/components/ui/FormModal";
import {
  LlmModelSelector,
  formatProvider,
  formatModelShort,
  EMPTY_LLM,
  type LlmPair,
} from "@/components/ui/LlmModelSelector";

const inputCls =
  "w-full bg-surface-1 border border-border-subtle rounded-lg px-3 py-2 text-xs text-text-primary placeholder-text-muted focus:outline-none focus:ring-1 focus:ring-accent focus:border-accent transition-colors";

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
      <span className="block text-[10px] text-text-muted italic">
        System defaults
      </span>
    );
  }
  return (
    <span className="block overflow-hidden">
      {lines.map((l) => (
        <span
          key={l.label}
          className="block text-[10px] text-text-tertiary leading-tight truncate"
        >
          <span className="text-text-muted">{l.label}:</span> {l.text}
        </span>
      ))}
    </span>
  );
}

const ROLE_STYLES: Record<string, string> = {
  owner: "bg-warning-muted text-warning",
  editor: "bg-accent-muted text-accent",
  viewer: "bg-surface-2 text-text-tertiary",
};

function AccessModal({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panelRef.current?.focus();
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      role="dialog"
      aria-modal="true"
      aria-label="Manage project access"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className="w-full max-w-md mx-4 animate-in fade-in zoom-in-95 duration-150 outline-none"
      >
        <InviteManager projectId={projectId} onClose={onClose} />
      </div>
    </div>
  );
}

interface ProjectSelectorProps {
  createRequested?: boolean;
  onCreateHandled?: () => void;
}

export function ProjectSelector({ createRequested, onCreateHandled }: ProjectSelectorProps) {
  const sshKeys = useAppStore((s) => s.sshKeys);
  const projects = useAppStore((s) => s.projects);
  const activeProject = useAppStore((s) => s.activeProject);
  const setProjects = useAppStore((s) => s.setProjects);
  const setActiveProject = useAppStore((s) => s.setActiveProject);
  const setConnections = useAppStore((s) => s.setConnections);
  const setActiveConnection = useAppStore((s) => s.setActiveConnection);
  const clearMessages = useAppStore((s) => s.clearMessages);
  const setChatSessions = useAppStore((s) => s.setChatSessions);
  const setActiveSession = useAppStore((s) => s.setActiveSession);
  const setUserRole = useAppStore((s) => s.setUserRole);
  const triggerProjectEdit = useAppStore((s) => s.triggerProjectEdit);
  const setTriggerProjectEdit = useAppStore((s) => s.setTriggerProjectEdit);
  const canCreate = useAuthStore((s) => s.user?.can_create_projects ?? false);
  const [showCreate, setShowCreate] = useState(false);
  const [showAccessRequest, setShowAccessRequest] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [managingAccessId, setManagingAccessId] = useState<string | null>(null);
  const [form, setForm] = useState<ProjectFormState>({ ...EMPTY_FORM });
  const [checking, setChecking] = useState(false);
  const [selectingId, setSelectingId] = useState<string | null>(null);
  const selectSeqRef = useRef(0);
  const [accessResult, setAccessResult] = useState<RepoCheckResult | null>(
    null,
  );
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [listLoading, setListLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api.projects
      .list()
      .then((p) => { if (!cancelled) setProjects(p); })
      .catch((err) => {
        if (!cancelled) toast(
          err instanceof Error ? err.message : "Failed to load projects",
          "error",
        );
      })
      .finally(() => { if (!cancelled) setListLoading(false); });
    return () => { cancelled = true; };
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
    if (!triggerProjectEdit || !activeProject) return;
    setTriggerProjectEdit(false);
    setEditingId(activeProject.id);
    setForm(projectToForm(activeProject));
    setShowCreate(false);
    setAccessResult(null);
    setChecking(false);
  }, [triggerProjectEdit, activeProject, setTriggerProjectEdit]);

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

  useEffect(() => {
    if (createRequested) {
      if (canCreate) {
        setEditingId(null);
        resetForm();
        setShowCreate(true);
      } else {
        setShowAccessRequest(true);
      }
      onCreateHandled?.();
    }
  }, [createRequested, onCreateHandled, canCreate]);

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
      toast("Project created", "success");
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Failed to create project",
        "error",
      );
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
        projects: state.projects.map((p) =>
          p.id === updated.id ? updated : p,
        ),
        ...(state.activeProject?.id === updated.id
          ? { activeProject: updated }
          : {}),
      }));
      setEditingId(null);
      resetForm();
      toast("Project updated", "success");
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Failed to update project",
        "error",
      );
    }
  };

  const handleSelect = async (project: Project) => {
    invalidateRestore();
    const seq = ++selectSeqRef.current;
    setSelectingId(project.id);
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
      if (seq !== selectSeqRef.current) return;
      setConnections(conns);
      setActiveConnection(conns[0] || null);
      setChatSessions(sessions);

      if (sessions.length === 0) {
        try {
          const welcome = await api.chat.ensureWelcome(project.id, conns[0]?.id);
          if (seq !== selectSeqRef.current) return;
          const welcomeSession = { id: welcome.id, project_id: welcome.project_id, title: welcome.title, connection_id: welcome.connection_id };
          setChatSessions([welcomeSession]);
          setActiveSession(welcomeSession);
          const msgs = await api.chat.getMessages(welcome.id);
          if (seq !== selectSeqRef.current) return;
          const mapped = msgs.map((m) => {
            let meta: Record<string, unknown> = {};
            try { meta = m.metadata_json ? JSON.parse(m.metadata_json) : {}; } catch { /* ignore */ }
            return {
              id: m.id,
              role: m.role as "user" | "assistant" | "system",
              content: m.content,
              responseType: (meta.response_type as "text" | "sql_result" | "knowledge" | "error") || undefined,
              metadataJson: m.metadata_json || undefined,
              timestamp: new Date(m.created_at).getTime(),
            };
          });
          useAppStore.getState().setMessages(mapped);
        } catch { /* welcome session is best-effort */ }
      }
    } catch (err) {
      if (seq !== selectSeqRef.current) return;
      setConnections([]);
      setActiveConnection(null);
      setChatSessions([]);
      toast(
        err instanceof Error ? err.message : "Failed to load project data",
        "error",
      );
    } finally {
      if (seq === selectSeqRef.current) setSelectingId(null);
    }
  };

  const handleDelete = async (e: React.MouseEvent, project: Project) => {
    e.stopPropagation();
    if (
      !(await confirmAction(`Delete project "${project.name}"?`, {
        severity: "critical",
        detail:
          "This will permanently delete ALL connections, chat history, rules, knowledge base, and indexed data for this project.",
        confirmText: project.name,
      }))
    ) return;
    try {
      await api.projects.delete(project.id);
      const wasActive = useAppStore.getState().activeProject?.id === project.id;
      useAppStore.setState((state) => ({
        projects: state.projects.filter((p) => p.id !== project.id),
      }));
      if (wasActive) {
        setActiveProject(null);
        setConnections([]);
        setActiveConnection(null);
        setChatSessions([]);
        setActiveSession(null);
        clearMessages();
      }
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Failed to delete project",
        "error",
      );
    }
  };

  const isFormOpen = showCreate || editingId !== null;

  const handleCancel = () => {
    setEditingId(null);
    setShowCreate(false);
    resetForm();
  };

  const formUI = (
    <div className="space-y-2.5">
      <div>
        <input
          value={form.name}
          onChange={(e) => {
            setForm({ ...form, name: e.target.value });
            setNameError("");
          }}
          placeholder="Project name"
          aria-label="Project name"
          maxLength={255}
          className={`${inputCls} ${nameError ? "border-error ring-1 ring-error" : ""}`}
        />
        {nameError && (
          <p className="text-[10px] text-error mt-1 px-1">{nameError}</p>
        )}
      </div>
      <div className="space-y-1">
        <input
          value={form.repoUrl}
          onChange={(e) => setForm({ ...form, repoUrl: e.target.value })}
          placeholder="Git repo URL (optional)"
          aria-label="Git repo URL"
          className={inputCls}
        />
        {form.repoUrl.trim() && (
          <div className="flex items-center gap-1.5 px-1 min-h-[18px]">
            {checking && (
              <span className="text-[10px] text-text-muted animate-pulse">
                Checking access...
              </span>
            )}
            {!checking && accessResult?.accessible && (
              <span className="text-[10px] text-success flex items-center gap-1">
                <Icon name="check" size={10} />
                Access verified
                {accessResult.branches.length > 0 && (
                  <span className="text-text-muted ml-1">
                    ({accessResult.branches.length} branch
                    {accessResult.branches.length !== 1 ? "es" : ""})
                  </span>
                )}
              </span>
            )}
            {!checking && accessResult && !accessResult.accessible && (
              <span
                className="text-[10px] text-error flex items-center gap-1"
                title={accessResult.error || undefined}
              >
                <Icon name="x" size={10} />
                {accessResult.error || "Access denied"}
              </span>
            )}
            {!checking &&
              !accessResult &&
              isSshUrl(form.repoUrl) &&
              !form.sshKeyId &&
              sshKeys.length === 0 && (
                <span className="text-[10px] text-warning">
                  SSH URL detected — add an SSH key first
                </span>
              )}
            {!checking &&
              !accessResult &&
              isSshUrl(form.repoUrl) &&
              !form.sshKeyId &&
              sshKeys.length > 1 && (
                <span className="text-[10px] text-warning">
                  Select an SSH key to verify access
                </span>
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
            aria-label="SSH key"
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
              aria-label="Branch"
            >
              {accessResult.branches.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          ) : (
            <input
              value={form.branch}
              onChange={(e) => setForm({ ...form, branch: e.target.value })}
              placeholder="Branch (default: main)"
              aria-label="Branch"
              className={inputCls}
            />
          )}
        </>
      )}
      <details open={!!editingId} className="group/llm">
        <summary className="flex items-center gap-1.5 cursor-pointer select-none py-1 text-[11px] font-medium text-text-secondary hover:text-text-primary transition-colors">
          <Icon
            name="chevron-right"
            size={12}
            className="text-text-muted transition-transform group-open/llm:rotate-90"
          />
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
                className="w-3 h-3 rounded border-border-default bg-surface-1 text-accent focus:ring-1 focus:ring-accent focus:ring-offset-0"
              />
              <span className="text-[10px] text-text-muted">
                Use Agent model
              </span>
            </label>
          </div>
        </div>
      </details>
      <div className="flex gap-2 pt-1">
        <button
          onClick={editingId ? handleUpdate : handleCreate}
          className="flex-1 px-3 py-2 bg-accent text-white text-xs font-medium rounded-lg hover:bg-accent-hover transition-colors"
        >
          {editingId ? "Save Changes" : "Create"}
        </button>
        {editingId && (
          <button
            onClick={() => {
              setEditingId(null);
              resetForm();
            }}
            className="px-3 py-2 text-text-tertiary hover:text-text-primary text-xs transition-colors"
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );

  return (
    <div className="px-1">
      <FormModal
        open={isFormOpen}
        onClose={handleCancel}
        title={editingId ? "Edit Project" : "New Project"}
        maxWidth="max-w-lg"
      >
        {formUI}
      </FormModal>

      {listLoading && <Spinner />}
      {!listLoading && projects.length === 0 && !isFormOpen && (
        <p className="text-[11px] text-text-muted px-3 py-2">No projects yet</p>
      )}
      <div>
        {projects.map((p) => {
          const isActive = activeProject?.id === p.id;
          return (
            <div
              key={p.id}
              className={`group relative flex items-start gap-2 pl-3 pr-1.5 py-1.5 rounded-md transition-colors cursor-pointer ${
                isActive
                  ? "bg-surface-1"
                  : "hover:bg-surface-1"
              }`}
              onClick={() => handleSelect(p)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  handleSelect(p);
                }
              }}
            >
              {isActive && (
                <div className="absolute left-0.5 top-1/4 bottom-1/4 w-0.5 bg-accent rounded-full" />
              )}
              <div className="flex-1 min-w-0 py-0.5">
                <div className="flex items-center gap-1.5">
                  <span
                    className={`text-xs font-medium truncate ${
                      isActive
                        ? "text-text-primary"
                        : "text-text-secondary"
                    }`}
                  >
                    {p.name}
                  </span>
                  {selectingId === p.id && (
                    <Spinner />
                  )}
                  {p.user_role && (
                    <span
                      className={`shrink-0 px-1 py-0.5 rounded text-[10px] font-medium leading-none ${
                        ROLE_STYLES[p.user_role] || ROLE_STYLES.viewer
                      }`}
                    >
                      {p.user_role}
                    </span>
                  )}
                </div>
                {isActive && (
                  <div className="mt-0.5">
                    <LlmBadges project={p} />
                  </div>
                )}
              </div>
              {p.user_role === "owner" && (
                <div className="shrink-0 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity duration-150">
                  <ActionButton
                    icon="users"
                    title="Manage access"
                    onClick={(e) => {
                      e.stopPropagation();
                      setManagingAccessId(
                        managingAccessId === p.id ? null : p.id,
                      );
                    }}
                    variant="accent"
                    size="xs"
                  />
                  <ActionButton
                    icon="pencil"
                    title="Edit project"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleEdit(p);
                    }}
                    size="xs"
                  />
                  <ActionButton
                    icon="trash"
                    title="Delete project"
                    onClick={(e) => handleDelete(e, p)}
                    variant="danger"
                    size="xs"
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {managingAccessId && (
        <AccessModal
          projectId={managingAccessId}
          onClose={() => setManagingAccessId(null)}
        />
      )}

      <RequestAccessModal
        open={showAccessRequest}
        onClose={() => setShowAccessRequest(false)}
      />
    </div>
  );
}
