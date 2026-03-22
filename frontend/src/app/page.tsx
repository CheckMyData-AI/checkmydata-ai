"use client";

import { useState, useCallback } from "react";
import { Sidebar } from "@/components/Sidebar";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { AuthGate } from "@/components/auth/AuthGate";
import { LogPanel, PersistentLogToggle } from "@/components/log/LogPanel";
import { NotesPanel } from "@/components/notes/NotesPanel";
import { ActiveTasksWidget } from "@/components/tasks/ActiveTasksWidget";
import { OnboardingWizard } from "@/components/onboarding/OnboardingWizard";
import { BatchRunner } from "@/components/batch/BatchRunner";
import { useAppStore } from "@/stores/app-store";
import { useAuthStore } from "@/stores/auth-store";
import { useNotesStore } from "@/stores/notes-store";
import { useGlobalEvents } from "@/hooks/useGlobalEvents";
import { useRestoreState } from "@/hooks/useRestoreState";
import { useMobileLayout } from "@/hooks/useMobileLayout";
import { Icon } from "@/components/ui/Icon";
import { Tooltip } from "@/components/ui/Tooltip";
import { NotificationBell } from "@/components/ui/NotificationBell";
import { SectionErrorBoundary } from "@/components/ui/SectionErrorBoundary";

export default function Home() {
  const { activeProject, activeConnection, projects } = useAppStore();
  const { user } = useAuthStore();
  const { isOpen: notesOpen, toggleOpen: toggleNotes } = useNotesStore();
  const notesCount = useNotesStore((s) => s.notes.length);
  const [onboardingDismissed, setOnboardingDismissed] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [showBatchRunner, setShowBatchRunner] = useState(false);
  const isMobile = useMobileLayout();

  useGlobalEvents(!!user);
  useRestoreState(!!user);

  const showOnboarding =
    !!user && !user.is_onboarded && projects.length === 0 && !onboardingDismissed;

  const handleOnboardingComplete = useCallback(() => {
    setOnboardingDismissed(true);
  }, []);

  return (
    <AuthGate>
      {showOnboarding && <OnboardingWizard onComplete={handleOnboardingComplete} />}
      <main className="min-h-screen bg-surface-0 text-text-primary">
        <div className="flex h-screen flex-col">
          {/* Mobile header bar */}
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
            <div className="flex-1 flex flex-col min-h-0 relative">
              {/* Desktop content header - hidden on mobile */}
              <header className="hidden md:flex border-b border-border-subtle px-6 py-2.5 items-center justify-between bg-surface-0">
                <div className="flex items-center gap-3 min-w-0">
                  {activeProject ? (
                    <>
                      <div className="flex items-center gap-2 min-w-0">
                        <Icon name="folder-git" size={14} className="text-text-tertiary shrink-0" />
                        <h2 className="text-sm font-medium text-text-primary truncate">
                          {activeProject.name}
                        </h2>
                      </div>
                      {activeConnection && (
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
                    </>
                  ) : (
                    <span className="text-sm text-text-tertiary">
                      Select a project to get started
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <ActiveTasksWidget />
                  {activeProject && (
                    <>
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
                            <span className="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 rounded-full bg-accent text-white text-[8px] font-bold flex items-center justify-center">
                              {notesCount > 9 ? "9+" : notesCount}
                            </span>
                          )}
                        </button>
                      </Tooltip>
                    </>
                  )}
                </div>
              </header>
              <SectionErrorBoundary sectionName="Chat">
                <ChatPanel />
              </SectionErrorBoundary>
              <PersistentLogToggle />
            </div>
            {!isMobile && (
              <SectionErrorBoundary sectionName="Notes">
                <NotesPanel />
              </SectionErrorBoundary>
            )}
          </div>
          <LogPanel />
        </div>
        {showBatchRunner && (
          <BatchRunner onClose={() => setShowBatchRunner(false)} />
        )}
        {/* Mobile Notes Drawer */}
        {isMobile && notesOpen && (
          <div className="fixed inset-0 z-50 md:hidden">
            <div
              className="absolute inset-0 bg-black/50"
              onClick={toggleNotes}
            />
            <div className="absolute bottom-0 left-0 right-0 max-h-[80vh] bg-surface-0 border-t border-border-subtle rounded-t-2xl overflow-hidden flex flex-col animate-slide-up">
              <div className="flex items-center justify-between px-4 py-3 border-b border-border-subtle shrink-0">
                <h3 className="text-sm font-semibold text-text-primary">Saved Queries</h3>
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
    </AuthGate>
  );
}
