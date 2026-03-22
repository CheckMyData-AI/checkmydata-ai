"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type ProjectInvite, type ProjectMember } from "@/lib/api";
import { confirmAction } from "@/components/ui/ConfirmModal";
import { toast } from "@/stores/toast-store";
import { Spinner } from "@/components/ui/Spinner";

const inputCls =
  "w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-1.5 text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-blue-500";

const ROLE_COLORS: Record<string, string> = {
  owner: "bg-amber-500/20 text-amber-300",
  editor: "bg-blue-500/20 text-blue-300",
  viewer: "bg-zinc-500/20 text-zinc-300",
};

interface Props {
  projectId: string;
  onClose: () => void;
}

export function InviteManager({ projectId, onClose }: Props) {
  const [invites, setInvites] = useState<ProjectInvite[]>([]);
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("editor");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [refreshLoading, setRefreshLoading] = useState(true);

  const refresh = useCallback(async () => {
    setRefreshLoading(true);
    try {
      const [inv, mem] = await Promise.all([
        api.invites.list(projectId),
        api.invites.listMembers(projectId),
      ]);
      setInvites(inv);
      setMembers(mem);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load access data", "error");
    } finally {
      setRefreshLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleInvite = async () => {
    if (!email.trim()) return;
    setError("");
    setLoading(true);
    try {
      await api.invites.create(projectId, email.trim(), role);
      setEmail("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send invite");
    } finally {
      setLoading(false);
    }
  };

  const handleRevoke = async (inviteId: string) => {
    if (!(await confirmAction("Revoke this invite?"))) return;
    try {
      await api.invites.revoke(projectId, inviteId);
      await refresh();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to revoke invite", "error");
    }
  };

  const handleRemoveMember = async (userId: string) => {
    if (!(await confirmAction("Remove this member?"))) return;
    try {
      await api.invites.removeMember(projectId, userId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove member");
    }
  };

  return (
    <div className="space-y-3 p-3 bg-zinc-800/80 rounded-lg border border-zinc-700">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-medium text-zinc-300 uppercase tracking-wider">
          Manage Access
        </h4>
        <button
          onClick={onClose}
          aria-label="Close access manager"
          className="text-xs text-zinc-500 hover:text-zinc-300"
        >
          ✕
        </button>
      </div>

      {/* Invite form */}
      <div className="flex gap-2">
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email address"
          className={inputCls}
          onKeyDown={(e) => e.key === "Enter" && handleInvite()}
        />
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="bg-zinc-900 border border-zinc-700 rounded px-2 py-1.5 text-xs text-zinc-100 focus:outline-none"
        >
          <option value="editor">Editor</option>
          <option value="viewer">Viewer</option>
        </select>
        <button
          onClick={handleInvite}
          disabled={loading || !email.trim()}
          className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-500 disabled:opacity-50 whitespace-nowrap"
        >
          Invite
        </button>
      </div>
      {error && <p className="text-xs text-red-400">{error}</p>}
      {refreshLoading && <Spinner />}

      {/* Members */}
      {members.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wider">Members</p>
          {members.map((m) => (
            <div key={m.id} className="flex items-center justify-between py-1 px-2 bg-zinc-900/50 rounded text-xs">
              <div className="flex items-center gap-2">
                <span className="text-zinc-200">{m.email || m.user_id}</span>
                {m.display_name && (
                  <span className="text-zinc-500">({m.display_name})</span>
                )}
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${ROLE_COLORS[m.role] || ROLE_COLORS.viewer}`}>
                  {m.role}
                </span>
              </div>
              {m.role !== "owner" && (
                <button
                  onClick={() => handleRemoveMember(m.user_id)}
                  className="text-zinc-600 hover:text-red-400 text-[10px]"
                >
                  ×
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Pending invites */}
      {invites.filter((i) => i.status === "pending").length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wider">Pending Invites</p>
          {invites
            .filter((i) => i.status === "pending")
            .map((inv) => (
              <div key={inv.id} className="flex items-center justify-between py-1 px-2 bg-zinc-900/50 rounded text-xs">
                <div className="flex items-center gap-2">
                  <span className="text-zinc-300">{inv.email}</span>
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${ROLE_COLORS[inv.role] || ROLE_COLORS.viewer}`}>
                    {inv.role}
                  </span>
                  <span className="text-yellow-500/60 text-[10px]">pending</span>
                </div>
                <button
                  onClick={() => handleRevoke(inv.id)}
                  className="text-zinc-600 hover:text-red-400 text-[10px]"
                >
                  revoke
                </button>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
