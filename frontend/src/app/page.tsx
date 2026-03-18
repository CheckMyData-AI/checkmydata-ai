"use client";

import { Sidebar } from "@/components/Sidebar";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { AuthGate } from "@/components/auth/AuthGate";
import { LogPanel } from "@/components/log/LogPanel";
import { useAppStore } from "@/stores/app-store";
import { useAuthStore } from "@/stores/auth-store";
import { useGlobalEvents } from "@/hooks/useGlobalEvents";
import { useRestoreState } from "@/hooks/useRestoreState";
import { Icon } from "@/components/ui/Icon";

export default function Home() {
  const { activeProject, activeConnection } = useAppStore();
  const { user } = useAuthStore();

  useGlobalEvents(!!user);
  useRestoreState(!!user);

  return (
    <AuthGate>
      <main className="min-h-screen bg-surface-0 text-text-primary">
        <div className="flex h-screen flex-col">
          <div className="flex flex-1 min-h-0">
            <Sidebar />
            <div className="flex-1 flex flex-col min-h-0">
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
              </header>
              <ChatPanel />
            </div>
          </div>
          <LogPanel />
        </div>
      </main>
    </AuthGate>
  );
}
