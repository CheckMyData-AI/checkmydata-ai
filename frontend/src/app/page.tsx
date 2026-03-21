"use client";

import { useState, useCallback } from "react";
import { Sidebar } from "@/components/Sidebar";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { AuthGate } from "@/components/auth/AuthGate";
import { LogPanel, PersistentLogToggle } from "@/components/log/LogPanel";
import { NotesPanel } from "@/components/notes/NotesPanel";
import { ActiveTasksWidget } from "@/components/tasks/ActiveTasksWidget";
import { OnboardingWizard } from "@/components/onboarding/OnboardingWizard";
import { useAppStore } from "@/stores/app-store";
import { useAuthStore } from "@/stores/auth-store";
import { useNotesStore } from "@/stores/notes-store";
import { useGlobalEvents } from "@/hooks/useGlobalEvents";
import { useRestoreState } from "@/hooks/useRestoreState";
import { Icon } from "@/components/ui/Icon";
import { Tooltip } from "@/components/ui/Tooltip";

export default function Home() {
  const { activeProject, activeConnection, projects } = useAppStore();
  const { user } = useAuthStore();
  const { isOpen: notesOpen, toggleOpen: toggleNotes } = useNotesStore();
  const notesCount = useNotesStore((s) => s.notes.length);
  const [onboardingDismissed, setOnboardingDismissed] = useState(false);

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
          <div className="flex flex-1 min-h-0">
            <Sidebar />
            <div className="flex-1 flex flex-col min-h-0 relative">
              <header className="border-b border-border-subtle px-6 py-2.5 flex items-center justify-between bg-surface-0">
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
                  )}
                </div>
              </header>
              <ChatPanel />
              <PersistentLogToggle />
            </div>
            <NotesPanel />
          </div>
          <LogPanel />
        </div>
      </main>
    </AuthGate>
  );
}
