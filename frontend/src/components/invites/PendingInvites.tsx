"use client";

import { useEffect, useRef, useState } from "react";
import { api, type ProjectInvite } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";
import { Spinner } from "@/components/ui/Spinner";

export function PendingInvites() {
  const [invites, setInvites] = useState<ProjectInvite[]>([]);
  const [accepting, setAccepting] = useState<string | null>(null);
  const [declining, setDeclining] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const setProjects = useAppStore((s) => s.setProjects);
  const mountedRef = useRef(true);

  const load = async () => {
    try {
      const pending = await api.invites.listPending();
      if (mountedRef.current) setInvites(pending);
    } catch (err) {
      if (mountedRef.current && err instanceof Error && !err.message.includes("401") && !err.message.includes("Session expired")) {
        toast(err.message, "error");
      }
    } finally {
      if (mountedRef.current) setListLoading(false);
    }
  };

  useEffect(() => {
    load();
    return () => { mountedRef.current = false; };
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

  const handleDecline = async (inviteId: string) => {
    setDeclining(inviteId);
    try {
      await api.invites.decline(inviteId);
      setInvites((prev) => prev.filter((i) => i.id !== inviteId));
      toast("Invite declined", "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to decline invite", "error");
    } finally {
      setDeclining(null);
    }
  };

  if (listLoading) return <Spinner />;
  if (invites.length === 0) return null;

  return (
    <div className="space-y-1 p-2 bg-accent-muted border border-accent/20 rounded-lg">
      <p className="text-[10px] text-accent uppercase tracking-wider font-medium">
        Pending Invitations ({invites.length})
      </p>
      {invites.map((inv) => {
        const projectLabel = inv.project_name ?? "Project";
        const busy = accepting === inv.id || declining === inv.id;
        return (
          <div
            key={inv.id}
            className="flex items-center justify-between py-1.5 px-2 bg-surface-1 rounded text-xs"
          >
            <div className="flex-1 min-w-0">
              <span className="text-text-primary truncate block">
                {projectLabel} ({inv.role})
              </span>
            </div>
            <div className="ml-2 flex items-center gap-1">
              <button
                onClick={() => handleDecline(inv.id)}
                disabled={busy}
                aria-label={`Decline invitation to ${projectLabel}`}
                className="px-2 py-1 text-text-secondary text-[10px] rounded hover:text-text-primary hover:bg-surface-2 disabled:opacity-50 transition-colors"
              >
                {declining === inv.id ? "..." : "Decline"}
              </button>
              <button
                onClick={() => handleAccept(inv.id)}
                disabled={busy}
                aria-label={`Accept invitation to ${projectLabel}`}
                className="px-2 py-1 bg-accent text-white text-[10px] rounded hover:bg-accent-hover disabled:opacity-50 transition-colors"
              >
                {accepting === inv.id ? "..." : "Accept"}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
