"use client";

import { useEffect, useState } from "react";
import { api, type ProjectInvite } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";
import { Spinner } from "@/components/ui/Spinner";

export function PendingInvites() {
  const [invites, setInvites] = useState<ProjectInvite[]>([]);
  const [accepting, setAccepting] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const setProjects = useAppStore((s) => s.setProjects);

  const load = async () => {
    try {
      const pending = await api.invites.listPending();
      setInvites(pending);
    } catch (err) {
      if (err instanceof Error && !err.message.includes("401") && !err.message.includes("Session expired")) {
        toast(err.message, "error");
      }
    } finally {
      setListLoading(false);
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
      toast("Invite accepted", "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to accept invite", "error");
    } finally {
      setAccepting(null);
    }
  };

  if (listLoading) return <Spinner />;
  if (invites.length === 0) return null;

  return (
    <div className="space-y-1 p-2 bg-accent-muted border border-accent/20 rounded-lg">
      <p className="text-[10px] text-accent uppercase tracking-wider font-medium">
        Pending Invitations ({invites.length})
      </p>
      {invites.map((inv) => (
        <div
          key={inv.id}
          className="flex items-center justify-between py-1.5 px-2 bg-surface-1 rounded text-xs"
        >
          <div className="flex-1 min-w-0">
            <span className="text-text-primary truncate block">
              Project invite ({inv.role})
            </span>
          </div>
          <button
            onClick={() => handleAccept(inv.id)}
            disabled={accepting === inv.id}
            className="ml-2 px-2 py-1 bg-accent text-white text-[10px] rounded hover:bg-accent-hover disabled:opacity-50 transition-colors"
          >
            {accepting === inv.id ? "..." : "Accept"}
          </button>
        </div>
      ))}
    </div>
  );
}
