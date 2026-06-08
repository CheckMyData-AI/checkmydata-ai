"use client";

import { Suspense, useState, useCallback, useRef, useMemo, useEffect } from "react";
import dynamic from "next/dynamic";
import { Sidebar } from "@/components/Sidebar";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { AuthGate } from "@/components/auth/AuthGate";
import { ProjectOverview } from "@/components/projects/ProjectOverview";
import { SettingsPanel } from "@/components/settings/SettingsPanel";
import { ConnectionsPanel } from "@/components/connections/ConnectionsPanel";
import { useAppStore } from "@/stores/app-store";
import { useAppPanel } from "@/hooks/useAppPanel";

const LogPanel = dynamic(
  () => import("@/components/log/LogPanel").then((m) => m.LogPanel),
  { ssr: false },
);
const PersistentLogToggle = dynamic(
  () => import("@/components/log/LogPanel").then((m) => m.PersistentLogToggle),
  { ssr: false },
);
const NotesPanel = dynamic(
  () => import("@/components/notes/NotesPanel").then((m) => m.NotesPanel),
  { ssr: false },
);
const ReasoningPanel = dynamic(
  () => import("@/components/chat/ReasoningPanel").then((m) => m.ReasoningPanel),
  { ssr: false },
);
const ActiveTasksWidget = dynamic(
  () => import("@/components/tasks/ActiveTasksWidget").then((m) => m.ActiveTasksWidget),
  { ssr: false },
);
const OnboardingWizard = dynamic(
  () => import("@/components/onboarding/OnboardingWizard").then((m) => m.OnboardingWizard),
  { ssr: false },
);
const BatchRunner = dynamic(
  () => import("@/components/batch/BatchRunner").then((m) => m.BatchRunner),
  { ssr: false },
);
const LogsScreen = dynamic(
  () => import("@/components/logs/LogsScreen").then((m) => m.LogsScreen),
  { ssr: false },
);
import { useAuthStore } from "@/stores/auth-store";
import { useNotesStore } from "@/stores/notes-store";
import { useGlobalEvents } from "@/hooks/useGlobalEvents";
import { useRestoreState } from "@/hooks/useRestoreState";
import { useRefreshOnFocus } from "@/hooks/useRefreshOnFocus";
import { useMobileLayout } from "@/hooks/useMobileLayout";
import { useDialogA11y } from "@/hooks/useDialogA11y";
import { Icon } from "@/components/ui/Icon";
import { Tooltip } from "@/components/ui/Tooltip";
import { NotificationBell } from "@/components/ui/NotificationBell";
import { SectionErrorBoundary } from "@/components/ui/SectionErrorBoundary";

function AppPageContent() {
  const activeProject = useAppStore((s) => s.activeProject);
  const activeConnection = useAppStore((s) => s.activeConnection);
  const activeSession = useAppStore((s) => s.activeSession);
  const messages = useAppStore((s) => s.messages);
  const projects = useAppStore((s) => s.projects);
  const user = useAuthStore((s) => s.user);
  const notesOpen = useNotesStore((s) => s.isOpen);
  const toggleNotes = useNotesStore((s) => s.toggleOpen);
  const notesCount = useNotesStore((s) => s.notes.length);
  const [onboardingDismissed, setOnboardingDismissed] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [showBatchRunner, setShowBatchRunner] = useState(false);
  const isMobile = useMobileLayout();
  const notesDrawerRef = useRef<HTMLDivElement>(null);
  const { panel, setPanel } = useAppPanel();

  useDialogA11y({
    open: isMobile && notesOpen,
    onClose: toggleNotes,
    panelRef: notesDrawerRef,
  });

  useGlobalEvents(!!user);
  useRestoreState(!!user);
  useRefreshOnFocus(!!user);

  const effectivePanel = useMemo(() => {
    if (panel === "logs") return "logs";
    if (panel === "settings") return "settings";
    if (panel === "connections") return "connections";
    if (panel === "overview") return "overview";
    if (panel === "chat") return "chat";

    if (!activeProject) return null;
    if (activeSession || messages.length > 0) return "chat";
    return "overview";
  }, [panel, activeProject, activeSession, messages.length]);

  useEffect(() => {
    const store = useAppStore.getState();
    if (effectivePanel === "logs" && !store.logsOpen) {
      store.setLogsOpen(true);
    } else if (effectivePanel !== "logs" && store.logsOpen) {
      store.setLogsOpen(false);
    }
  }, [effectivePanel]);

  const showOnboarding =
    !!user && !user.is_onboarded && projects.length === 0 && !onboardingDismissed;

  const handleOnboardingComplete = useCallback(() => {
    setOnboardingDismissed(true);
  }, []);

  const closePanel = useCallback(() => {
    if (activeSession || messages.length > 0) {
      setPanel("chat");
    } else {
      setPanel(null);
    }
  }, [activeSession, messages.length, setPanel]);

  const renderCenterPanel = () => {
    if (effectivePanel === "logs") {
      return (
        <SectionErrorBoundary sectionName="Request History">
          <LogsScreen onClose={closePanel} />
        </SectionErrorBoundary>
      );
    }
    if (effectivePanel === "settings") {
      return (
        <SectionErrorBoundary sectionName="Settings">
          <SettingsPanel onClose={closePanel} onNavigate={setPanel} />
        </SectionErrorBoundary>
      );
    }
    if (effectivePanel === "connections") {
      return (
        <SectionErrorBoundary sectionName="Connections">
          <ConnectionsPanel />
        </SectionErrorBoundary>
      );
    }
    if (effectivePanel === "overview") {
      return (
        <SectionErrorBoundary sectionName="Overview">
          <ProjectOverview />
        </SectionErrorBoundary>
      );
    }
    return (
      <SectionErrorBoundary sectionName="Chat">
        <ChatPanel />
      </SectionErrorBoundary>
    );
  };

  return (
    <>
      {showOnboarding && <OnboardingWizard onComplete={handleOnboardingComplete} />}
      <main className="min-h-screen bg-surface-0 text-text-primary">
        <div className="flex h-screen flex-col">
          {isMobile && (
            <div className="sticky top-0 z-40 flex items-center justify-between border-b border-border-subtle bg-surface-0 px-3 py-2.5 md:hidden">
              <button
                onClick={() => setSidebarOpen(true)}
                aria-label="Open menu"
                className="p-2 -ml-1 rounded-md text-text-secondary hover:bg-surface-2 transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center"
              >
                <Icon name="menu" size={20} />
              </button>
              <h1 className="text-sm font-semibold text-text-primary truncate">
                {activeProject?.name || "CheckMyData"}
              </h1>
              <div className="flex items-center gap-1">
                {activeProject && (
                  <button
                    onClick={toggleNotes}
                    aria-label={notesOpen ? "Hide saved queries" : "Show saved queries"}
                    className={`p-2 rounded-md transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center ${
                      notesOpen
                        ? "text-accent bg-accent-muted"
                        : "text-text-secondary hover:bg-surface-2"
                    }`}
                  >
                    <Icon name="bookmark" size={18} />
                  </button>
                )}
                <NotificationBell />
              </div>
            </div>
          )}

          <div className="flex flex-1 min-h-0">
            <SectionErrorBoundary sectionName="Sidebar">
              {isMobile ? (
                <Sidebar
                  isMobile
                  isOpen={sidebarOpen}
                  onClose={() => setSidebarOpen(false)}
                />
              ) : (
                <Sidebar />
              )}
            </SectionErrorBoundary>
            <div id="main-content" className="flex-1 flex flex-col min-h-0 relative overflow-hidden">
              <header className="hidden md:flex border-b border-border-subtle px-6 py-2.5 items-center justify-between bg-surface-0">
                <div className="flex items-center gap-3 min-w-0">
                  {activeProject ? (
                    <>
                      <div className="flex items-center gap-2 min-w-0">
                        <Icon name="folder-git" size={14} className="text-text-tertiary shrink-0" />
                        <h1 className="text-sm font-medium text-text-primary truncate">
                          {activeProject.name}
                        </h1>
                      </div>
                      {activeConnection && effectivePanel === "chat" && (
                        <>
                          <span className="text-text-muted">/</span>
                          <div className="flex items-center gap-1.5 min-w-0">
                            <Icon name="database" size={12} className="text-text-tertiary shrink-0" />
                            <span className="text-xs text-text-secondary truncate">
                              {activeConnection.name}
                            </span>
                            <span className="text-[10px] text-text-muted uppercase font-mono">
                              {activeConnection.db_type}
                            </span>
                          </div>
                        </>
                      )}
                      {effectivePanel === "overview" && (
                        <span className="text-xs text-text-muted">Overview</span>
                      )}
                      {effectivePanel === "settings" && (
                        <span className="text-xs text-text-muted">Settings</span>
                      )}
                      {effectivePanel === "logs" && (
                        <span className="text-xs text-text-muted">Request History</span>
                      )}
                    </>
                  ) : (
                    <h1 className="text-sm font-medium text-text-tertiary">
                      Select a project to get started
                    </h1>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <ActiveTasksWidget />
                  {activeProject && (
                    <>
                      <Tooltip label="Project overview" position="bottom">
                        <button
                          onClick={() => setPanel("overview")}
                          aria-label="Open project overview"
                          className={`p-1.5 rounded-md transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                            effectivePanel === "overview"
                              ? "text-accent bg-accent-muted"
                              : "text-text-muted hover:text-text-secondary hover:bg-surface-2"
                          }`}
                        >
                          <Icon name="layout-dashboard" size={16} />
                        </button>
                      </Tooltip>
                      <Tooltip label="Settings" position="bottom">
                        <button
                          onClick={() => setPanel("settings")}
                          aria-label="Open settings"
                          className={`p-1.5 rounded-md transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                            effectivePanel === "settings"
                              ? "text-accent bg-accent-muted"
                              : "text-text-muted hover:text-text-secondary hover:bg-surface-2"
                          }`}
                        >
                          <Icon name="settings" size={16} />
                        </button>
                      </Tooltip>
                      <Tooltip label="Batch query runner" position="bottom">
                        <button
                          onClick={() => setShowBatchRunner(true)}
                          aria-label="Open batch query runner"
                          className="p-1.5 rounded-md transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent text-text-muted hover:text-text-secondary hover:bg-surface-2"
                        >
                          <Icon name="layers" size={16} />
                        </button>
                      </Tooltip>
                      <Tooltip label={notesOpen ? "Hide saved queries" : "Saved queries"} position="bottom">
                        <button
                          onClick={toggleNotes}
                          aria-label={notesOpen ? "Hide saved queries" : "Show saved queries"}
                          className={`relative p-1.5 rounded-md transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                            notesOpen
                              ? "text-accent bg-accent-muted"
                              : "text-text-muted hover:text-text-secondary hover:bg-surface-2"
                          }`}
                        >
                          <Icon name="bookmark" size={16} />
                          {notesCount > 0 && !notesOpen && (
                            <span className="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 rounded-full bg-accent text-white text-[10px] font-bold flex items-center justify-center">
                              {notesCount > 9 ? "9+" : notesCount}
                            </span>
                          )}
                        </button>
                      </Tooltip>
                    </>
                  )}
                </div>
              </header>
              <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
                {renderCenterPanel()}
              </div>
              <PersistentLogToggle />
            </div>
            {!isMobile && (
              <>
                <SectionErrorBoundary sectionName="Notes">
                  <NotesPanel />
                </SectionErrorBoundary>
                <SectionErrorBoundary sectionName="Reasoning">
                  <ReasoningPanel />
                </SectionErrorBoundary>
              </>
            )}
          </div>
          <LogPanel />
        </div>
        {showBatchRunner && (
          <BatchRunner onClose={() => setShowBatchRunner(false)} />
        )}
        {isMobile && notesOpen && (
          <div className="fixed inset-0 z-50 md:hidden">
            <div
              className="absolute inset-0 bg-black/60 animate-fade-in"
              onClick={toggleNotes}
              aria-hidden="true"
            />
            <div
              ref={notesDrawerRef}
              role="dialog"
              aria-modal="true"
              aria-labelledby="mobile-notes-title"
              className="absolute bottom-0 left-0 right-0 max-h-[80vh] bg-surface-0 border-t border-border-subtle rounded-t-2xl overflow-hidden flex flex-col animate-slide-up"
            >
              <div className="flex items-center justify-between px-4 py-3 border-b border-border-subtle shrink-0">
                <h3 id="mobile-notes-title" className="text-sm font-semibold text-text-primary">Saved Queries</h3>
                <button
                  onClick={toggleNotes}
                  aria-label="Close notes"
                  className="p-2 rounded-md text-text-muted hover:bg-surface-2 transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center"
                >
                  <Icon name="x" size={18} />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto">
                <SectionErrorBoundary sectionName="Notes">
                  <NotesPanel />
                </SectionErrorBoundary>
              </div>
            </div>
          </div>
        )}
      </main>
    </>
  );
}

export default function Home() {
  return (
    <AuthGate>
      <Suspense
        fallback={
          <div className="min-h-screen bg-surface-0 flex items-center justify-center">
            <p className="text-sm text-text-muted animate-pulse">Loading...</p>
          </div>
        }
      >
        <AppPageContent />
      </Suspense>
    </AuthGate>
  );
}
