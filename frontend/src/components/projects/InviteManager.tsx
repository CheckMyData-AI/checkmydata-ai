"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type ProjectInvite, type ProjectMember } from "@/lib/api";
import { confirmAction } from "@/components/ui/ConfirmModal";
import { toast } from "@/stores/toast-store";
import { Spinner } from "@/components/ui/Spinner";

const inputCls =
  "w-full bg-surface-1 border border-border-default rounded-lg px-3 py-1.5 text-xs text-text-primary placeholder-text-muted focus:outline-none focus:ring-1 focus:ring-accent";

const ROLE_COLORS: Record<string, string> = {
  owner: "bg-warning-muted text-warning",
  editor: "bg-accent-muted text-accent-hover",
  viewer: "bg-surface-3/20 text-text-primary",
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
    <div className="space-y-3 p-3 bg-surface-2/80 rounded-xl border border-border-default">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-medium text-text-primary uppercase tracking-wider">
          Manage Access
        </h4>
        <button
          onClick={onClose}
          aria-label="Close access manager"
          className="text-xs text-text-tertiary hover:text-text-primary"
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
          aria-label="Invite email address"
          aria-required="true"
          className={inputCls}
          onKeyDown={(e) => e.key === "Enter" && handleInvite()}
        />
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          aria-label="Member role"
          className="bg-surface-1 border border-border-default rounded-lg px-2 py-1.5 text-xs text-text-primary focus:outline-none"
        >
          <option value="editor">Editor</option>
          <option value="viewer">Viewer</option>
        </select>
        <button
          onClick={handleInvite}
          disabled={loading || !email.trim()}
          className="px-3 py-1.5 bg-accent text-white text-xs rounded hover:bg-accent-hover disabled:opacity-50 whitespace-nowrap"
        >
          Invite
        </button>
      </div>
      {error && <p className="text-xs text-error">{error}</p>}
      {refreshLoading && <Spinner />}

      {/* Members */}
      {members.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] text-text-tertiary uppercase tracking-wider">Members</p>
          {members.map((m) => (
            <div key={m.id} className="flex items-center justify-between py-1 px-2 bg-surface-1/50 rounded text-xs">
              <div className="flex items-center gap-2">
                <span className="text-text-primary">{m.email || m.user_id}</span>
                {m.display_name && (
                  <span className="text-text-tertiary">({m.display_name})</span>
                )}
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${ROLE_COLORS[m.role] || ROLE_COLORS.viewer}`}>
                  {m.role}
                </span>
              </div>
              {m.role !== "owner" && (
                <button
                  onClick={() => handleRemoveMember(m.user_id)}
                  aria-label="Remove member"
                  className="text-text-muted hover:text-error text-[10px]"
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
          <p className="text-[10px] text-text-tertiary uppercase tracking-wider">Pending Invites</p>
          {invites
            .filter((i) => i.status === "pending")
            .map((inv) => (
              <div key={inv.id} className="flex items-center justify-between py-1 px-2 bg-surface-1/50 rounded text-xs">
                <div className="flex items-center gap-2">
                  <span className="text-text-primary">{inv.email}</span>
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${ROLE_COLORS[inv.role] || ROLE_COLORS.viewer}`}>
                    {inv.role}
                  </span>
                  <span className="text-warning/60 text-[10px]">pending</span>
                </div>
                <button
                  onClick={() => handleRevoke(inv.id)}
                  className="text-text-muted hover:text-error text-[10px]"
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
