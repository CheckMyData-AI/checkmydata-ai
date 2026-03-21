"use client";

import Link from "next/link";
import { SshKeyManager } from "./ssh/SshKeyManager";
import { ProjectSelector } from "./projects/ProjectSelector";
import { ConnectionSelector } from "./connections/ConnectionSelector";
import { SyncStatusIndicator } from "./connections/SyncStatusIndicator";
import { ChatSessionList } from "./chat/ChatSessionList";
import { ChatSearch } from "./chat/ChatSearch";
import { RulesManager } from "./rules/RulesManager";
import { KnowledgeDocs } from "./knowledge/KnowledgeDocs";
import { WorkflowProgress } from "./workflow/WorkflowProgress";
import { PendingInvites } from "./invites/PendingInvites";
import { useAppStore } from "@/stores/app-store";
import { useAuthStore } from "@/stores/auth-store";
import { api } from "@/lib/api";
import type { RepoStatus, UpdateCheck } from "@/lib/api";
import { useState, useEffect, useCallback, useRef } from "react";
import { Icon } from "./ui/Icon";
import { Tooltip } from "./ui/Tooltip";
import { SidebarSection, useSectionCollapse } from "./ui/SidebarSection";
import { useLogStore } from "@/stores/log-store";
import { AccountMenu } from "./auth/AccountMenu";
import { UsageStatsPanel } from "./usage/UsageStatsPanel";
import { FeedbackAnalyticsPanel } from "./analytics/FeedbackAnalyticsPanel";
import { ScheduleManager } from "./schedules/ScheduleManager";
import { DashboardList } from "./dashboards/DashboardList";
import { NotificationBell } from "./ui/NotificationBell";

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

function getStoredCollapsed(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return localStorage.getItem("sidebar_main_collapsed") === "true";
  } catch {
    return false;
  }
}

interface SidebarProps {
  isMobile?: boolean;
  isOpen?: boolean;
  onClose?: () => void;
}

export function Sidebar({ isMobile = false, isOpen = false, onClose }: SidebarProps) {
  const { activeProject, sshKeys, setSshKeys, projects, connections, restoringState } =
    useAppStore();
  const { user, logout } = useAuthStore();
  const [collapsed, setCollapsed] = useState(isMobile ? false : getStoredCollapsed);
  const drawerRef = useRef<HTMLElement>(null);

  const [indexing, setIndexing] = useState(false);
  const [indexResult, setIndexResult] = useState<string | null>(null);
  const [indexWorkflowId, setIndexWorkflowId] = useState<string | null>(null);
  const [repoStatus, setRepoStatus] = useState<RepoStatus | null>(null);
  const [updateCheck, setUpdateCheck] = useState<UpdateCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const dismissTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
    if (dismissTimerRef.current) {
      clearTimeout(dismissTimerRef.current);
      dismissTimerRef.current = null;
    }
    setRepoStatus(null);
    setUpdateCheck(null);
    setIndexResult(null);
    setIndexWorkflowId(null);
    loadStatus();
  }, [activeProject?.id, loadStatus]);

  const handleIndex = async () => {
    if (!activeProject) return;
    if (dismissTimerRef.current) {
      clearTimeout(dismissTimerRef.current);
      dismissTimerRef.current = null;
    }
    setIndexing(true);
    setIndexResult(null);
    setIndexWorkflowId(null);
    setUpdateCheck(null);
    try {
      const result = await api.repos.index(activeProject.id);
      setIndexWorkflowId(result.workflow_id);
      useLogStore.getState().setOpen(true);
    } catch (err) {
      setIndexResult(
        `Error: ${err instanceof Error ? err.message : "Unknown"}`,
      );
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
      if (activeProject) {
        useAppStore.getState().clearReadinessCache(activeProject.id);
      }

      if (dismissTimerRef.current) clearTimeout(dismissTimerRef.current);
      const delay = status === "failed" ? 15_000 : 5_000;
      dismissTimerRef.current = setTimeout(() => {
        setIndexWorkflowId(null);
        setIndexResult(null);
        dismissTimerRef.current = null;
      }, delay);
    },
    [loadStatus, activeProject],
  );

  const handleCheckUpdates = async () => {
    if (!activeProject) return;
    setChecking(true);
    setUpdateCheck(null);
    try {
      const uc = await api.repos.checkUpdates(activeProject.id);
      setUpdateCheck(uc);
    } catch {
      setUpdateCheck({
        has_updates: false,
        commits_behind: 0,
        message: "Check failed",
      });
    } finally {
      setChecking(false);
    }
  };

  useEffect(() => {
    api.sshKeys
      .list()
      .then(setSshKeys)
      .catch(() => {});
  }, [setSshKeys]);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem("sidebar_main_collapsed", String(next));
      return next;
    });
  };

  const showOnboarding = projects.length === 0;

  const sshCollapse = useSectionCollapse("ssh-keys");
  const projectsCollapse = useSectionCollapse("projects");
  const repoCollapse = useSectionCollapse("repository");
  const connCollapse = useSectionCollapse("connections");
  const chatCollapse = useSectionCollapse("chat-history");
  const rulesCollapse = useSectionCollapse("rules", false);
  const schedulesCollapse = useSectionCollapse("schedules", false);
  const dashboardsCollapse = useSectionCollapse("dashboards", false);
  const knowledgeCollapse = useSectionCollapse("knowledge", false);
  const usageCollapse = useSectionCollapse("usage", false);
  const analyticsCollapse = useSectionCollapse("analytics", false);

  const projectsRef = useRef<HTMLDivElement>(null);
  const repoRef = useRef<HTMLDivElement>(null);
  const connRef = useRef<HTMLDivElement>(null);

  const focusSection = useAppStore((s) => s.focusSidebarSection);
  const setFocusSection = useAppStore((s) => s.setFocusSidebarSection);

  useEffect(() => {
    if (!focusSection) return;
    const map: Record<string, { forceOpen: () => void; ref: React.RefObject<HTMLDivElement | null> }> = {
      projects: { forceOpen: projectsCollapse.forceOpen, ref: projectsRef },
      repository: { forceOpen: repoCollapse.forceOpen, ref: repoRef },
      connections: { forceOpen: connCollapse.forceOpen, ref: connRef },
    };
    const target = map[focusSection];
    if (target) {
      if (collapsed) {
        setCollapsed(false);
        localStorage.setItem("sidebar_main_collapsed", "false");
      }
      target.forceOpen();
      setTimeout(() => target.ref.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 150);
    }
    setFocusSection(null);
  }, [focusSection, setFocusSection, collapsed, projectsCollapse.forceOpen, repoCollapse.forceOpen, connCollapse.forceOpen]);

  const userInitials = user
    ? (user.display_name || user.email)
        .split(/[\s@]/)
        .slice(0, 2)
        .map((s) => s[0]?.toUpperCase() || "")
        .join("")
    : "";

  const repoSection = activeProject?.repo_url ? (
    <div className="space-y-2 px-1">
      {repoStatus && (
        <div className="text-xs text-text-secondary space-y-1.5 bg-surface-1 rounded-lg p-2.5 border border-border-subtle">
          {repoStatus.last_indexed_commit ? (
            <>
              <div className="flex justify-between items-center">
                <span className="text-text-tertiary">Commit</span>
                <span className="text-text-primary font-mono text-[11px]">
                  {repoStatus.last_indexed_commit.slice(0, 7)}
                </span>
              </div>
              {repoStatus.last_indexed_at && (
                <div className="flex justify-between items-center">
                  <span className="text-text-tertiary">Indexed</span>
                  <span className="text-text-secondary">
                    {timeAgo(repoStatus.last_indexed_at)}
                  </span>
                </div>
              )}
              <div className="flex justify-between items-center">
                <span className="text-text-tertiary">Branch</span>
                <span className="text-text-secondary font-mono text-[11px]">
                  {repoStatus.branch}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-text-tertiary">Docs</span>
                <span className="text-text-secondary">
                  {repoStatus.total_documents}
                </span>
              </div>
            </>
          ) : (
            <p className="text-text-muted italic text-[11px]">
              Not yet indexed
            </p>
          )}
          {repoStatus.is_indexing && (
            <p className="text-warning text-[11px] flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-warning animate-pulse-dot" />
              Indexing in progress...
            </p>
          )}
        </div>
      )}

      <div className="flex gap-1.5">
        <button
          onClick={handleIndex}
          disabled={indexing}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs bg-surface-2 text-text-secondary rounded-lg hover:bg-surface-3 hover:text-text-primary disabled:opacity-50 transition-colors"
        >
          <Icon name="refresh-cw" size={12} className={indexing ? "animate-spin" : ""} />
          {indexing ? "Indexing..." : "Index Repo"}
        </button>
        {repoStatus?.last_indexed_commit && (
          <button
            onClick={handleCheckUpdates}
            disabled={checking || indexing}
            title="Check for new commits"
            aria-label="Check for new commits"
            className="px-3 py-2 text-xs bg-surface-2 text-text-tertiary rounded-lg hover:bg-surface-3 hover:text-text-secondary disabled:opacity-50 transition-colors"
          >
            {checking ? "..." : "Check"}
          </button>
        )}
      </div>

      {updateCheck && (
        <p
          className={`text-[11px] px-1 ${
            updateCheck.has_updates ? "text-warning" : "text-success"
          }`}
        >
          {updateCheck.message}
          {updateCheck.has_updates && updateCheck.commits_behind > 0 && (
            <button
              onClick={handleIndex}
              disabled={indexing}
              className="ml-1.5 underline hover:text-warning/80"
            >
              Re-index now
            </button>
          )}
        </p>
      )}

      {indexWorkflowId && (
        <WorkflowProgress
          workflowId={indexWorkflowId}
          compact
          onComplete={handleIndexComplete}
        />
      )}
      {indexResult && (
        <p
          className={`text-[11px] px-1 ${
            indexResult.startsWith("Error") ? "text-error" : "text-success"
          }`}
        >
          {indexResult}
        </p>
      )}
    </div>
  ) : null;

  useEffect(() => {
    if (!isMobile || !isOpen) return;
    const el = drawerRef.current;
    if (!el) return;
    const focusable = el.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    first?.focus();

    function trapFocus(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose?.();
        return;
      }
      if (e.key !== "Tab") return;
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    }
    document.addEventListener("keydown", trapFocus);
    return () => document.removeEventListener("keydown", trapFocus);
  }, [isMobile, isOpen, onClose]);

  if (isMobile) {
    return (
      <>
        {/* Backdrop */}
        <div
          className={`fixed inset-0 z-50 bg-black/60 transition-opacity duration-200 ${
            isOpen ? "opacity-100" : "opacity-0 pointer-events-none"
          }`}
          onClick={onClose}
          aria-hidden="true"
        />
        {/* Drawer */}
        <aside
          ref={drawerRef}
          role="dialog"
          aria-modal="true"
          aria-label="Navigation"
          className={`fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] bg-surface-0 border-r border-border-subtle flex flex-col transition-transform duration-200 ease-out ${
            isOpen ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          {/* Mobile drawer header with close button */}
          <div className="shrink-0 px-3 py-3 border-b border-border-subtle flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-accent to-blue-700 flex items-center justify-center shrink-0">
              <Icon name="zap" size={16} className="text-white" />
            </div>
            <div className="flex-1 min-w-0">
              <h1 className="text-sm font-semibold text-text-primary leading-tight">
                DB Agent
              </h1>
              <p className="text-[10px] text-text-muted leading-tight">
                AI Query Assistant
              </p>
            </div>
            <button
              onClick={onClose}
              aria-label="Close menu"
              className="p-2 rounded-md text-text-muted hover:text-text-secondary hover:bg-surface-2 transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center"
            >
              <Icon name="x" size={18} />
            </button>
          </div>

          {/* Scrollable body */}
          <div className="flex-1 overflow-y-auto overflow-x-hidden sidebar-scroll py-2 space-y-1">
            <PendingInvites />

            {showOnboarding && (
              <div className="mx-3 p-3 bg-accent-muted border border-accent/20 rounded-lg space-y-2.5 animate-slide-in-left">
                <p className="text-[11px] font-semibold text-accent">Getting Started</p>
                <div className="space-y-2 text-[11px]">
                  {[
                    { done: sshKeys.length > 0, step: 1, label: "Add an SSH key" },
                    { done: projects.length > 0, step: 2, label: "Create your first project" },
                    { done: connections.length > 0, step: 3, label: "Add a database connection" },
                  ].map((item) => (
                    <div key={item.step} className="flex items-center gap-2.5">
                      <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-medium shrink-0 ${
                        item.done ? "bg-success-muted text-success" : "bg-surface-2 text-text-muted"
                      }`}>
                        {item.done ? <Icon name="check" size={10} /> : item.step}
                      </span>
                      <span className={item.done ? "text-text-muted line-through" : "text-text-secondary"}>
                        {item.label}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="px-4 pt-3 pb-1">
              <span className="text-[9px] text-text-muted/60 uppercase tracking-wider">Setup</span>
            </div>

            <SidebarSection icon="key" title="SSH Keys" open={sshCollapse.open} onToggle={sshCollapse.toggle} count={sshKeys.length} collapsed={false}>
              <SshKeyManager />
            </SidebarSection>

            <div ref={projectsRef}>
              <SidebarSection icon="folder-git" title="Projects" open={projectsCollapse.open} onToggle={projectsCollapse.toggle} count={projects.length} collapsed={false}>
                <ProjectSelector />
              </SidebarSection>
            </div>

            {activeProject && (
              <>
                <div className="px-4 pt-3 pb-1">
                  <div className="border-t border-border-subtle/50 mb-3" />
                  <span className="text-[9px] text-text-muted/60 uppercase tracking-wider">Workspace</span>
                </div>

                {activeProject.repo_url && (
                  <div ref={repoRef}>
                    <SidebarSection icon="git-branch" title="Repository" open={repoCollapse.open} onToggle={repoCollapse.toggle} collapsed={false}>
                      {repoSection}
                    </SidebarSection>
                  </div>
                )}

                <div ref={connRef}>
                  <SidebarSection icon="database" title="Connections" open={connCollapse.open} onToggle={connCollapse.toggle} count={connections.length} collapsed={false}>
                    <ConnectionSelector />
                    <SyncStatusIndicator />
                  </SidebarSection>
                </div>

                <SidebarSection icon="message-square" title="Chat History" open={chatCollapse.open} onToggle={chatCollapse.toggle} collapsed={false}>
                  {restoringState ? (
                    <div className="px-3 py-2 space-y-1.5">
                      {[1, 2, 3].map((i) => (
                        <div key={i} className="h-4 rounded bg-surface-2 animate-pulse" style={{ width: `${80 - i * 15}%` }} />
                      ))}
                    </div>
                  ) : (
                    <>
                      {activeProject && <ChatSearch />}
                      <ChatSessionList />
                    </>
                  )}
                </SidebarSection>

                <SidebarSection icon="file-text" title="Custom Rules" open={rulesCollapse.open} onToggle={rulesCollapse.toggle} collapsed={false}>
                  <RulesManager />
                </SidebarSection>

                <SidebarSection icon="clock" title="Schedules" open={schedulesCollapse.open} onToggle={schedulesCollapse.toggle} collapsed={false}>
                  <ScheduleManager />
                </SidebarSection>

                <SidebarSection icon="book-open" title="Knowledge" open={knowledgeCollapse.open} onToggle={knowledgeCollapse.toggle} collapsed={false}>
                  <KnowledgeDocs />
                </SidebarSection>

                <SidebarSection icon="activity" title="Usage" open={usageCollapse.open} onToggle={usageCollapse.toggle} collapsed={false}>
                  <UsageStatsPanel />
                </SidebarSection>

                <SidebarSection icon="bar-chart-2" title="Analytics" open={analyticsCollapse.open} onToggle={analyticsCollapse.toggle} collapsed={false}>
                  <FeedbackAnalyticsPanel projectId={activeProject.id} />
                </SidebarSection>
              </>
            )}
          </div>

          {/* Account footer (mobile) */}
          {user && (
            <div className="relative shrink-0 px-3 py-2.5 border-t border-border-subtle space-y-2">
              <div className="flex items-center gap-2.5">
                {user.picture_url ? (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img src={user.picture_url} alt="" referrerPolicy="no-referrer" className="w-7 h-7 rounded-full border border-border-default shrink-0 object-cover" />
                ) : (
                  <div className="w-7 h-7 rounded-full bg-surface-2 border border-border-default flex items-center justify-center shrink-0">
                    <span className="text-[10px] font-semibold text-text-secondary">{userInitials}</span>
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-text-primary truncate leading-tight">{user.display_name || user.email.split("@")[0]}</p>
                  <p className="text-[10px] text-text-muted truncate leading-tight">{user.email}</p>
                </div>
                <AccountMenu />
              </div>
              <div className="flex items-center gap-2 px-0.5">
                <Link href="/terms" className="text-[10px] text-text-muted hover:text-text-tertiary transition-colors">Terms</Link>
                <span className="text-text-muted/40 text-[10px]">&middot;</span>
                <Link href="/privacy" className="text-[10px] text-text-muted hover:text-text-tertiary transition-colors">Privacy</Link>
              </div>
            </div>
          )}
        </aside>
      </>
    );
  }

  return (
    <aside
      className={`shrink-0 border-r border-border-subtle bg-surface-0 flex flex-col h-full overflow-hidden transition-all duration-200 ease-out ${
        collapsed ? "w-16" : "w-64"
      }`}
    >
      {/* Header */}
      <div className="shrink-0 px-3 py-3 border-b border-border-subtle flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-accent to-blue-700 flex items-center justify-center shrink-0">
          <Icon name="zap" size={16} className="text-white" />
        </div>
        {!collapsed && (
          <div className="flex-1 min-w-0 animate-fade-in">
            <h1 className="text-sm font-semibold text-text-primary leading-tight">
              DB Agent
            </h1>
            <p className="text-[10px] text-text-muted leading-tight">
              AI Query Assistant
            </p>
          </div>
        )}
        {!collapsed && <NotificationBell />}
        <Tooltip label={collapsed ? "Expand sidebar" : "Collapse sidebar"} position="bottom">
          <button
            onClick={toggleCollapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="p-1.5 rounded-md text-text-muted hover:text-text-secondary hover:bg-surface-2 transition-colors shrink-0 outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <Icon
              name="sidebar-left"
              size={16}
            />
          </button>
        </Tooltip>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden sidebar-scroll py-2 space-y-1">
        <PendingInvites />

        {/* Onboarding guide */}
        {showOnboarding && !collapsed && (
          <div className="mx-3 p-3 bg-accent-muted border border-accent/20 rounded-lg space-y-2.5 animate-slide-in-left">
            <p className="text-[11px] font-semibold text-accent">
              Getting Started
            </p>
            <div className="space-y-2 text-[11px]">
              {[
                {
                  done: sshKeys.length > 0,
                  step: 1,
                  label: "Add an SSH key",
                },
                {
                  done: projects.length > 0,
                  step: 2,
                  label: "Create your first project",
                },
                {
                  done: connections.length > 0,
                  step: 3,
                  label: "Add a database connection",
                },
              ].map((item) => (
                <div key={item.step} className="flex items-center gap-2.5">
                  <span
                    className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-medium shrink-0 ${
                      item.done
                        ? "bg-success-muted text-success"
                        : "bg-surface-2 text-text-muted"
                    }`}
                  >
                    {item.done ? (
                      <Icon name="check" size={10} />
                    ) : (
                      item.step
                    )}
                  </span>
                  <span
                    className={
                      item.done
                        ? "text-text-muted line-through"
                        : "text-text-secondary"
                    }
                  >
                    {item.label}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* SETUP group */}
        {!collapsed && (
          <div className="px-4 pt-3 pb-1">
            <span className="text-[9px] text-text-muted/60 uppercase tracking-wider">
              Setup
            </span>
          </div>
        )}

        <SidebarSection
          icon="key"
          title="SSH Keys"
          open={sshCollapse.open}
          onToggle={sshCollapse.toggle}
          count={sshKeys.length}
          collapsed={collapsed}
        >
          <SshKeyManager />
        </SidebarSection>

        <div ref={projectsRef}>
          <SidebarSection
            icon="folder-git"
            title="Projects"
            open={projectsCollapse.open}
            onToggle={projectsCollapse.toggle}
            count={projects.length}
            collapsed={collapsed}
          >
            <ProjectSelector />
          </SidebarSection>
        </div>

        {activeProject && (
          <>
            {/* WORKSPACE group */}
            {!collapsed && (
              <div className="px-4 pt-3 pb-1">
                <div className="border-t border-border-subtle/50 mb-3" />
                <span className="text-[9px] text-text-muted/60 uppercase tracking-wider">
                  Workspace
                </span>
              </div>
            )}
            {collapsed && (
              <div className="px-4 py-1">
                <div className="border-t border-border-subtle/50" />
              </div>
            )}

            {activeProject.repo_url && (
              <div ref={repoRef}>
                <SidebarSection
                  icon="git-branch"
                  title="Repository"
                  open={repoCollapse.open}
                  onToggle={repoCollapse.toggle}
                  collapsed={collapsed}
                >
                  {repoSection}
                </SidebarSection>
              </div>
            )}

            <div ref={connRef}>
              <SidebarSection
                icon="database"
                title="Connections"
                open={connCollapse.open}
                onToggle={connCollapse.toggle}
                count={connections.length}
                collapsed={collapsed}
              >
                <ConnectionSelector />
                <SyncStatusIndicator />
              </SidebarSection>
            </div>

            <SidebarSection
              icon="message-square"
              title="Chat History"
              open={chatCollapse.open}
              onToggle={chatCollapse.toggle}
              collapsed={collapsed}
            >
              {restoringState ? (
                <div className="px-3 py-2 space-y-1.5">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-4 rounded bg-surface-2 animate-pulse" style={{ width: `${80 - i * 15}%` }} />
                  ))}
                </div>
              ) : (
                <>
                  {!collapsed && activeProject && <ChatSearch />}
                  <ChatSessionList />
                </>
              )}
            </SidebarSection>

            <SidebarSection
              icon="file-text"
              title="Custom Rules"
              open={rulesCollapse.open}
              onToggle={rulesCollapse.toggle}
              collapsed={collapsed}
            >
              <RulesManager />
            </SidebarSection>

            <SidebarSection
              icon="clock"
              title="Schedules"
              open={schedulesCollapse.open}
              onToggle={schedulesCollapse.toggle}
              collapsed={collapsed}
            >
              <ScheduleManager />
            </SidebarSection>

            <SidebarSection
              icon="layout"
              title="Dashboards"
              open={dashboardsCollapse.open}
              onToggle={dashboardsCollapse.toggle}
              collapsed={collapsed}
            >
              <DashboardList />
            </SidebarSection>

            <SidebarSection
              icon="book-open"
              title="Knowledge"
              open={knowledgeCollapse.open}
              onToggle={knowledgeCollapse.toggle}
              collapsed={collapsed}
            >
              <KnowledgeDocs />
            </SidebarSection>

            <SidebarSection
              icon="activity"
              title="Usage"
              open={usageCollapse.open}
              onToggle={usageCollapse.toggle}
              collapsed={collapsed}
            >
              <UsageStatsPanel />
            </SidebarSection>

            <SidebarSection
              icon="bar-chart-2"
              title="Analytics"
              open={analyticsCollapse.open}
              onToggle={analyticsCollapse.toggle}
              collapsed={collapsed}
            >
              <FeedbackAnalyticsPanel projectId={activeProject.id} />
            </SidebarSection>
          </>
        )}
      </div>

      {/* Account footer */}
      {user && !collapsed && (
        <div className="relative shrink-0 px-3 py-2.5 border-t border-border-subtle animate-fade-in space-y-2">
          <div className="flex items-center gap-2.5">
            {user.picture_url ? (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img
                src={user.picture_url}
                alt=""
                referrerPolicy="no-referrer"
                className="w-7 h-7 rounded-full border border-border-default shrink-0 object-cover"
              />
            ) : (
              <div className="w-7 h-7 rounded-full bg-surface-2 border border-border-default flex items-center justify-center shrink-0">
                <span className="text-[10px] font-semibold text-text-secondary">
                  {userInitials}
                </span>
              </div>
            )}
            <div className="flex-1 min-w-0">
              <p className="text-xs text-text-primary truncate leading-tight">
                {user.display_name || user.email.split("@")[0]}
              </p>
              <p className="text-[10px] text-text-muted truncate leading-tight">
                {user.email}
              </p>
            </div>
            <AccountMenu />
          </div>
          <div className="flex items-center gap-2 px-0.5">
            <Link href="/terms" className="text-[10px] text-text-muted hover:text-text-tertiary transition-colors">
              Terms
            </Link>
            <span className="text-text-muted/40 text-[10px]">&middot;</span>
            <Link href="/privacy" className="text-[10px] text-text-muted hover:text-text-tertiary transition-colors">
              Privacy
            </Link>
          </div>
        </div>
      )}
      {user && collapsed && (
        <div className="shrink-0 px-2 py-2.5 border-t border-border-subtle flex justify-center">
          <Tooltip label={`${user.email} — Sign out`} position="top">
            <button
              onClick={logout}
              aria-label="Sign out"
              className="w-8 h-8 rounded-full bg-surface-2 border border-border-default flex items-center justify-center hover:border-accent/50 hover:bg-surface-3 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <span className="text-[10px] font-semibold text-text-secondary">
                {userInitials}
              </span>
            </button>
          </Tooltip>
        </div>
      )}
    </aside>
  );
}
