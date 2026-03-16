"use client";

import { useEffect, useState } from "react";
import { api, type ProjectInvite } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";

export function PendingInvites() {
  const [invites, setInvites] = useState<ProjectInvite[]>([]);
  const [accepting, setAccepting] = useState<string | null>(null);
  const setProjects = useAppStore((s) => s.setProjects);

  const load = async () => {
    try {
      const pending = await api.invites.listPending();
      setInvites(pending);
    } catch {
      /* no-op if not logged in */
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleAccept = async (inviteId: string) => {
    setAccepting(inviteId);
    try {
      await api.invites.accept(inviteId);
      setInvites((prev) => prev.filter((i) => i.id !== inviteId));
      const projects = await api.projects.list();
      setProjects(projects);
    } catch (err) {
      console.error("Failed to accept invite", err);
    } finally {
      setAccepting(null);
    }
  };

  if (invites.length === 0) return null;

  return (
    <div className="space-y-1 p-2 bg-blue-500/10 border border-blue-500/20 rounded-lg">
      <p className="text-[10px] text-blue-300 uppercase tracking-wider font-medium">
        Pending Invitations ({invites.length})
      </p>
      {invites.map((inv) => (
        <div
          key={inv.id}
          className="flex items-center justify-between py-1.5 px-2 bg-zinc-900/50 rounded text-xs"
        >
          <div className="flex-1 min-w-0">
            <span className="text-zinc-200 truncate block">
              Project invite ({inv.role})
            </span>
          </div>
          <button
            onClick={() => handleAccept(inv.id)}
            disabled={accepting === inv.id}
            className="ml-2 px-2 py-1 bg-blue-600 text-white text-[10px] rounded hover:bg-blue-500 disabled:opacity-50"
          >
            {accepting === inv.id ? "..." : "Accept"}
          </button>
        </div>
      ))}
    </div>
  );
}
