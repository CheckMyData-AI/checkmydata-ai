"use client";

import Link from "next/link";
import { ProjectSelector } from "./projects/ProjectSelector";
import { RailSourceList } from "./connections/RailSourceList";
import { ChatSessionList } from "./chat/ChatSessionList";
import { ChatSearch } from "./chat/ChatSearch";
import { SidebarGroup, useSidebarGroupCollapse } from "./ui/SidebarGroup";
import { SidebarNavLauncher } from "./ui/SidebarNavLauncher";
import { useAppPanel } from "@/hooks/useAppPanel";
import { PendingInvites } from "./invites/PendingInvites";
import { AttentionGroup } from "./attention/AttentionGroup";
import { useAppStore } from "@/stores/app-store";
import { useAuthStore } from "@/stores/auth-store";
import { api } from "@/lib/api";
import { useState, useEffect, useCallback, useRef } from "react";
import { Icon } from "./ui/Icon";
import { Tooltip } from "./ui/Tooltip";
import { SidebarSection, useSectionCollapse } from "./ui/SidebarSection";
import { toast } from "@/stores/toast-store";
import { AccountMenu } from "./auth/AccountMenu";
import { NotificationBell } from "./ui/NotificationBell";
import { usePermission } from "@/hooks/usePermission";

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
  const { isOwner } = usePermission();
  const activeProject = useAppStore((s) => s.activeProject);
  const setSshKeys = useAppStore((s) => s.setSshKeys);
  const projects = useAppStore((s) => s.projects);
  const connections = useAppStore((s) => s.connections);
  const restoringState = useAppStore((s) => s.restoringState);
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const [collapsed, setCollapsed] = useState(isMobile ? false : getStoredCollapsed);
  const drawerRef = useRef<HTMLElement>(null);

  // The repository's status, its index trigger, its progress and its update check
  // all lived here. They are gone from the rail, not from the product: live progress
  // with cancel and retry is the Knowledge Health panel of the project overview
  // (SCN-062), a failed or reaped run reaches the `Needs you` group (SCN-150), and
  // the repository itself is a group in the data workspace (SCN-129). The rail
  // switches and reports; it does not run things. SCN-133/SCN-149.

  useEffect(() => {
    api.sshKeys
      .list()
      .then(setSshKeys)
      .catch((err) => toast(err instanceof Error ? err.message : "Failed to load SSH keys", "error"));
  }, [setSshKeys]);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try { localStorage.setItem("sidebar_main_collapsed", String(next)); } catch { /* */ }
      return next;
    });
  };

  const showOnboarding = projects.length === 0;

  const projectsCollapse = useSectionCollapse("projects");
  const connCollapse = useSectionCollapse("connections");
  const chatCollapse = useSectionCollapse("chat-history");

  const { setPanel } = useAppPanel();
  const setupGroup = useSidebarGroupCollapse("setup");
  const workspaceGroup = useSidebarGroupCollapse("workspace");

  const openRequestHistory = useCallback(() => {
    setPanel("logs");
    onClose?.();
  }, [setPanel, onClose]);

  const [projCreateReq, setProjCreateReq] = useState(false);
  const [chatCreateReq, setChatCreateReq] = useState(false);

  const onProjCreated = useCallback(() => setProjCreateReq(false), []);
  const onChatCreated = useCallback(() => setChatCreateReq(false), []);

  const projectsRef = useRef<HTMLDivElement>(null);
  const connRef = useRef<HTMLDivElement>(null);

  const focusSection = useAppStore((s) => s.focusSidebarSection);
  const setFocusSection = useAppStore((s) => s.setFocusSidebarSection);

  useEffect(() => {
    if (!focusSection) return;
    const map: Record<string, { forceOpen: () => void; ref: React.RefObject<HTMLDivElement | null> }> = {
      projects: { forceOpen: projectsCollapse.forceOpen, ref: projectsRef },
      connections: { forceOpen: connCollapse.forceOpen, ref: connRef },
    };
    const target = map[focusSection];
    if (target) {
      if (collapsed) {
        setCollapsed(false);
        try { localStorage.setItem("sidebar_main_collapsed", "false"); } catch { /* */ }
      }
      target.forceOpen();
      setTimeout(() => target.ref.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 150);
    }
    setFocusSection(null);
  }, [focusSection, setFocusSection, collapsed, projectsCollapse.forceOpen, connCollapse.forceOpen]);

  const userInitials = user
    ? (user.display_name || user.email)
        .split(/[\s@]/)
        .slice(0, 2)
        .map((s) => s[0]?.toUpperCase() || "")
        .join("")
    : "";


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
          className={`fixed inset-0 z-50 lg-scrim transition-opacity duration-200 ${
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
            <div className="w-8 h-8 rounded-control bg-ink text-on-ink flex items-center justify-center shrink-0">
              <Icon name="zap" size={16} className="text-white" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-text-primary leading-tight">
                DB Agent
              </p>
              <p className="text-kicker text-text-muted leading-tight">
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
            <AttentionGroup />

            {showOnboarding && (
              <div className="mx-3 p-3 bg-accent-muted border border-accent/20 rounded-lg space-y-2.5 animate-slide-in-left">
                <p className="text-meta font-semibold text-accent">Getting Started</p>
                <div className="space-y-2 text-meta">
                  {[
                    { done: projects.length > 0, step: 1, label: "Create your first project" },
                    { done: connections.length > 0, step: 2, label: "Add a database connection" },
                    { done: projects.some((p) => p.repo_url), step: 3, label: "Connect your code (optional)" },
                  ].map((item) => (
                    <div key={item.step} className="flex items-center gap-2.5">
                      <span className={`w-5 h-5 rounded-full flex items-center justify-center text-kicker font-medium shrink-0 ${
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

            <SidebarGroup
              label="Setup"
              collapsed={setupGroup.collapsed}
              onToggle={setupGroup.toggle}
            >


              {/* Fixed, never collapsible: this is where the user IS, and a rail that can
                  hide your location answers neither of its two questions (SCN-149). */}
              <div ref={projectsRef} className="px-1 pb-1">
                <div className="flex items-center justify-between px-2 py-1">
                  <span className="text-kicker uppercase tracking-wider text-text-muted font-medium">
                    Project
                  </span>
                  <button
                    type="button"
                    onClick={() => setProjCreateReq(true)}
                    className="text-meta text-text-tertiary hover:text-text-secondary transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent rounded"
                  >
                    New
                  </button>
                </div>
                <ProjectSelector createRequested={projCreateReq} onCreateHandled={onProjCreated} />
              </div>
            </SidebarGroup>

            {activeProject && (
              <>
                <SidebarGroup
                  label="Workspace"
                  collapsed={workspaceGroup.collapsed}
                  onToggle={workspaceGroup.toggle}
                >

                  <div ref={connRef}>
                    <SidebarSection icon="database" title="Connections" open={connCollapse.open} onToggle={connCollapse.toggle} count={connections.length} collapsed={false}>
                      <RailSourceList />
                    </SidebarSection>
                  </div>

                  <SidebarSection icon="message-square" title="Recent" open={chatCollapse.open} onToggle={chatCollapse.toggle} collapsed={false} action={{ label: "New chat", onClick: () => { setChatCreateReq(true); setPanel("chat"); } }}>
                    {restoringState ? (
                      <div className="px-3 py-2 space-y-1.5">
                        {[1, 2, 3].map((i) => (
                          <div key={i} className="h-4 rounded bg-surface-2 animate-pulse" style={{ width: `${80 - i * 15}%` }} />
                        ))}
                      </div>
                    ) : (
                      <>
                        {activeProject && <ChatSearch />}
                        <ChatSessionList createRequested={chatCreateReq} onCreateHandled={onChatCreated} />
                      </>
                    )}
                  </SidebarSection>




                </SidebarGroup>

                <div className="mb-1">
                  <SidebarNavLauncher
                    icon="message-square"
                    title="Chat"
                    onClick={() => setPanel("chat")}
                  />
                  <SidebarNavLauncher
                    icon="database"
                    title="Data"
                    subtitle="Sources, repository, docs"
                    onClick={() => setPanel("connections")}
                  />
                  <SidebarNavLauncher
                    icon="book-open"
                    title="Knowledge"
                    subtitle="Docs, insights, rules"
                    onClick={() => setPanel("knowledge")}
                  />
                  <SidebarNavLauncher
                    icon="layout"
                    title="Dashboards"
                    onClick={() => setPanel("dashboards")}
                  />
                  {isOwner && (
                    <SidebarNavLauncher
                      icon="terminal"
                      title="Activity"
                      subtitle="Runs, errors and traces"
                      onClick={openRequestHistory}
                    />
                  )}
                </div>
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
                    <span className="text-kicker font-semibold text-text-secondary">{userInitials}</span>
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-text-primary truncate leading-tight">{user.display_name || user.email?.split("@")[0] || "User"}</p>
                  <p className="text-kicker text-text-muted truncate leading-tight">{user.email || ""}</p>
                </div>
                <AccountMenu />
              </div>
              <div className="flex items-center gap-2 px-0.5">
                <Link href="/terms" className="text-kicker text-text-muted hover:text-text-tertiary transition-colors">Terms</Link>
                <span className="text-text-muted/40 text-kicker">&middot;</span>
                <Link href="/privacy" className="text-kicker text-text-muted hover:text-text-tertiary transition-colors">Privacy</Link>
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
        <div className="w-8 h-8 rounded-control bg-ink text-on-ink flex items-center justify-center shrink-0">
          <Icon name="zap" size={16} className="text-white" />
        </div>
        {!collapsed && (
          <div className="flex-1 min-w-0 animate-fade-in">
            <p className="text-sm font-semibold text-text-primary leading-tight">
              DB Agent
            </p>
            <p className="text-kicker text-text-muted leading-tight">
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
        {!collapsed && <PendingInvites />}
        {!collapsed && <AttentionGroup />}

        {/* Onboarding guide */}
        {showOnboarding && !collapsed && (
          <div className="mx-3 p-3 bg-accent-muted border border-accent/20 rounded-lg space-y-2.5 animate-slide-in-left">
            <p className="text-meta font-semibold text-accent">
              Getting Started
            </p>
            <div className="space-y-2 text-meta">
              {[
                {
                  done: projects.length > 0,
                  step: 1,
                  label: "Create your first project",
                },
                {
                  done: connections.length > 0,
                  step: 2,
                  label: "Add a database connection",
                },
                {
                  done: projects.some((p) => p.repo_url),
                  step: 3,
                  label: "Connect your code (optional)",
                },
              ].map((item) => (
                <div key={item.step} className="flex items-center gap-2.5">
                  <span
                    className={`w-5 h-5 rounded-full flex items-center justify-center text-kicker font-medium shrink-0 ${
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

        <SidebarGroup
          label="Setup"
          collapsed={setupGroup.collapsed}
          onToggle={setupGroup.toggle}
          sidebarCollapsed={collapsed}
        >

          {/* Owner-scoped analytics-vendor secrets (GA4 service accounts &c.) —
              same list/add/delete rhythm as SSH Keys, and the only place a
              credential can be reviewed or removed once a connection exists. */}

          {/* Fixed, never collapsible: this is where the user IS, and a rail that can

              hide your location answers neither of its two questions (SCN-149). */}

          <div ref={projectsRef} className="px-1 pb-1">

            <div className="flex items-center justify-between px-2 py-1">

              <span className="text-kicker uppercase tracking-wider text-text-muted font-medium">

                Project

              </span>

              <button

                type="button"

                onClick={() => setProjCreateReq(true)}

                className="text-meta text-text-tertiary hover:text-text-secondary transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent rounded"

              >

                New

              </button>

            </div>

            <ProjectSelector createRequested={projCreateReq} onCreateHandled={onProjCreated} />

          </div>
        </SidebarGroup>

        {activeProject && (
          <>
            {/* Destinations, flat. These three used to be collapsible sections in this
                rail and are screens now — see SCN-151. Flat and not grouped on purpose:
                a thing you go to should cost one click, not an expand and a click. */}
            <div className="mb-1">
              <SidebarNavLauncher
                icon="message-square"
                title="Chat"
                onClick={() => setPanel("chat")}
                collapsed={collapsed}
              />
              <SidebarNavLauncher
                icon="database"
                title="Data"
                subtitle="Sources, repository, docs"
                onClick={() => setPanel("connections")}
                collapsed={collapsed}
              />
              <SidebarNavLauncher
                icon="book-open"
                title="Knowledge"
                subtitle="Docs, insights, rules"
                onClick={() => setPanel("knowledge")}
                collapsed={collapsed}
              />
              <SidebarNavLauncher
                icon="layout"
                title="Dashboards"
                onClick={() => setPanel("dashboards")}
                collapsed={collapsed}
              />
              {isOwner && (
                <SidebarNavLauncher
                  icon="terminal"
                  title="Activity"
                  subtitle="Runs, errors and traces"
                  onClick={openRequestHistory}
                  collapsed={collapsed}
                />
              )}
            </div>

            <SidebarGroup
              label="Workspace"
              collapsed={workspaceGroup.collapsed}
              onToggle={workspaceGroup.toggle}
              sidebarCollapsed={collapsed}
            >

              <div ref={connRef}>
                <SidebarSection
                  icon="database"
                  title="Connections"
                  open={connCollapse.open}
                  onToggle={connCollapse.toggle}
                  count={connections.length}
                  collapsed={collapsed}
                 
                >
                  <RailSourceList />
                </SidebarSection>
              </div>

              <SidebarSection
                icon="message-square"
                title="Recent"
                open={chatCollapse.open}
                onToggle={chatCollapse.toggle}
                collapsed={collapsed}
                action={{ label: "New chat", onClick: () => { setChatCreateReq(true); setPanel("chat"); } }}
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
                    <ChatSessionList createRequested={chatCreateReq} onCreateHandled={onChatCreated} />
                  </>
                )}
              </SidebarSection>




            </SidebarGroup>

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
                <span className="text-kicker font-semibold text-text-secondary">
                  {userInitials}
                </span>
              </div>
            )}
            <div className="flex-1 min-w-0">
              <p className="text-xs text-text-primary truncate leading-tight">
                {user.display_name || user.email?.split("@")[0] || "User"}
              </p>
              <p className="text-kicker text-text-muted truncate leading-tight">
                {user.email || ""}
              </p>
            </div>
            <AccountMenu />
          </div>
          <div className="flex items-center gap-2 px-0.5">
            <Link href="/terms" className="text-kicker text-text-muted hover:text-text-tertiary transition-colors">
              Terms
            </Link>
            <span className="text-text-muted/40 text-kicker">&middot;</span>
            <Link href="/privacy" className="text-kicker text-text-muted hover:text-text-tertiary transition-colors">
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
              <span className="text-kicker font-semibold text-text-secondary">
                {userInitials}
              </span>
            </button>
          </Tooltip>
        </div>
      )}
    </aside>
  );
}
