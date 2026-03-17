"use client";

import { Sidebar } from "@/components/Sidebar";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { AuthGate } from "@/components/auth/AuthGate";
import { LogPanel } from "@/components/log/LogPanel";
import { useAppStore } from "@/stores/app-store";
import { useAuthStore } from "@/stores/auth-store";
import { useGlobalEvents } from "@/hooks/useGlobalEvents";
import { useRestoreState } from "@/hooks/useRestoreState";

export default function Home() {
  const { activeProject, activeConnection } = useAppStore();
  const { user, logout } = useAuthStore();

  useGlobalEvents(!!user);
  useRestoreState(!!user);

  return (
    <AuthGate>
      <main className="min-h-screen bg-zinc-950 text-zinc-100">
        <div className="flex h-screen flex-col">
          <div className="flex flex-1 min-h-0">
            <Sidebar />
            <div className="flex-1 flex flex-col min-h-0">
              <header className="border-b border-zinc-800 px-6 py-3 flex items-center justify-between">
                <div>
                  <h2 className="text-sm font-medium text-zinc-300">
                    {activeProject ? activeProject.name : "Select a project"}
                  </h2>
                  {activeConnection && (
                    <p className="text-xs text-zinc-500">
                      {activeConnection.db_type} &middot; {activeConnection.name}
                    </p>
                  )}
                </div>
                {user && (
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-zinc-500">{user.email}</span>
                    <button
                      onClick={logout}
                      className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
                    >
                      Sign Out
                    </button>
                  </div>
                )}
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
