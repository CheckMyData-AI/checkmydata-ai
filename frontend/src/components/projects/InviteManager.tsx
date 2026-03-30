"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ProjectInvite, type ProjectMember } from "@/lib/api";
import { confirmAction } from "@/components/ui/ConfirmModal";
import { toast } from "@/stores/toast-store";
import { Spinner } from "@/components/ui/Spinner";
import { Icon } from "@/components/ui/Icon";

const inputCls =
  "w-full bg-surface-1 border border-border-default rounded-lg px-3 py-1.5 text-xs text-text-primary placeholder-text-muted focus:outline-none focus:ring-1 focus:ring-accent";

const ROLE_COLORS: Record<string, string> = {
  owner: "bg-warning-muted text-warning",
  editor: "bg-accent-muted text-accent-hover",
  viewer: "bg-surface-3/20 text-text-primary",
};

function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

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
  const [updatingRoleId, setUpdatingRoleId] = useState<string | null>(null);
  const [resending, setResending] = useState<string | null>(null);
  const [resentIds, setResentIds] = useState<Set<string>>(new Set());
  const resendTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  useEffect(() => {
    const timers = resendTimers.current;
    return () => {
      timers.forEach((t) => clearTimeout(t));
    };
  }, []);

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
      toast("Invite sent", "success");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send invite");
    } finally {
      setLoading(false);
    }
  };

  const handleRevoke = async (inviteId: string, inviteEmail: string) => {
    if (
      !(await confirmAction(`Delete invite for ${inviteEmail}?`, {
        detail: "This will revoke the pending invitation. You can re-invite later.",
        severity: "warning",
      }))
    )
      return;
    try {
      await api.invites.revoke(projectId, inviteId);
      toast("Invite deleted", "success");
      await refresh();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to revoke invite", "error");
    }
  };

  const handleResend = async (inviteId: string) => {
    setResending(inviteId);
    try {
      await api.invites.resend(projectId, inviteId);
      toast("Invite email resent", "success");
      setResentIds((prev) => new Set(prev).add(inviteId));
      const timer = setTimeout(() => {
        resendTimers.current.delete(inviteId);
        setResentIds((prev) => {
          const next = new Set(prev);
          next.delete(inviteId);
          return next;
        });
      }, 60_000);
      resendTimers.current.set(inviteId, timer);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to resend invite", "error");
    } finally {
      setResending(null);
    }
  };

  const handleRemoveMember = async (userId: string, memberEmail: string | null) => {
    if (
      !(await confirmAction(`Remove ${memberEmail || "this member"}?`, {
        detail:
          "They will lose access to this project immediately. You can re-invite them later.",
        severity: "warning",
      }))
    )
      return;
    try {
      await api.invites.removeMember(projectId, userId);
      toast("Member removed", "success");
      await refresh();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to remove member", "error");
    }
  };

  const handleRoleChange = async (userId: string, newRole: string, prevRole: string) => {
    setUpdatingRoleId(userId);
    setMembers((prev) =>
      prev.map((m) => (m.user_id === userId ? { ...m, role: newRole } : m)),
    );
    try {
      await api.invites.updateMemberRole(projectId, userId, newRole);
      toast("Role updated", "success");
    } catch (err) {
      setMembers((prev) =>
        prev.map((m) => (m.user_id === userId ? { ...m, role: prevRole } : m)),
      );
      toast(err instanceof Error ? err.message : "Failed to update role", "error");
    } finally {
      setUpdatingRoleId(null);
    }
  };

  const pendingInvites = invites.filter((i) => i.status === "pending");

  return (
    <div className="space-y-3 p-4 bg-surface-1 rounded-xl border border-border-default shadow-xl">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-medium text-text-primary uppercase tracking-wider">
          Manage Access
        </h4>
        <button
          onClick={onClose}
          aria-label="Close access manager"
          className="text-text-tertiary hover:text-text-primary transition-colors p-1"
        >
          <Icon name="x" size={14} />
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
          className="px-3 py-1.5 bg-accent text-white text-xs rounded-lg hover:bg-accent-hover disabled:opacity-50 whitespace-nowrap transition-colors"
        >
          Invite
        </button>
      </div>
      {error && <p className="text-xs text-error">{error}</p>}
      {refreshLoading && <Spinner />}

      {/* Members */}
      {members.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] text-text-tertiary uppercase tracking-wider">
            Members ({members.length})
          </p>
          {members.map((m) => (
            <div
              key={m.id}
              className="flex items-center justify-between py-1.5 px-2 bg-surface-1/50 rounded-lg text-xs"
            >
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <div className="min-w-0 flex-1">
                  <span className="text-text-primary truncate block">
                    {m.display_name || m.email || m.user_id}
                  </span>
                  {m.display_name && m.email && (
                    <span className="text-text-muted text-[10px] truncate block">
                      {m.email}
                    </span>
                  )}
                </div>
                {m.role === "owner" ? (
                  <span
                    className={`px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0 ${ROLE_COLORS.owner}`}
                  >
                    owner
                  </span>
                ) : (
                  <select
                    value={m.role}
                    onChange={(e) => handleRoleChange(m.user_id, e.target.value, m.role)}
                    disabled={updatingRoleId === m.user_id}
                    aria-label={`Change role for ${m.email || m.display_name || "member"}`}
                    className={`px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0 border-none cursor-pointer focus:outline-none focus:ring-1 focus:ring-accent transition-colors ${ROLE_COLORS[m.role] || ROLE_COLORS.viewer} ${updatingRoleId === m.user_id ? "opacity-50" : ""}`}
                  >
                    <option value="editor">editor</option>
                    <option value="viewer">viewer</option>
                  </select>
                )}
              </div>
              {m.role !== "owner" && (
                <button
                  onClick={() => handleRemoveMember(m.user_id, m.email)}
                  aria-label={`Remove ${m.email || m.display_name || "member"}`}
                  className="ml-2 px-2 py-0.5 text-[10px] text-text-muted hover:text-error hover:bg-error/10 rounded transition-colors shrink-0"
                >
                  Remove
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Pending invites */}
      {pendingInvites.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] text-text-tertiary uppercase tracking-wider">
            Pending Invites ({pendingInvites.length})
          </p>
          {pendingInvites.map((inv) => (
            <div
              key={inv.id}
              className="flex items-center justify-between py-1.5 px-2 bg-surface-1/50 rounded-lg text-xs"
            >
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <div className="min-w-0 flex-1">
                  <span className="text-text-primary truncate block">{inv.email}</span>
                  <span className="text-text-muted text-[10px]">
                    {inv.created_at ? `Sent ${relativeTime(inv.created_at)}` : "pending"}
                  </span>
                </div>
                <span
                  className={`px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0 ${ROLE_COLORS[inv.role] || ROLE_COLORS.viewer}`}
                >
                  {inv.role}
                </span>
              </div>
              <div className="flex items-center gap-1 ml-2 shrink-0">
                <button
                  onClick={() => handleResend(inv.id)}
                  disabled={resending === inv.id || resentIds.has(inv.id)}
                  aria-label={`Resend invite to ${inv.email}`}
                  className="px-2 py-0.5 text-[10px] text-accent hover:text-accent-hover hover:bg-accent/10 rounded transition-colors disabled:opacity-50 disabled:cursor-default"
                >
                  {resending === inv.id
                    ? "..."
                    : resentIds.has(inv.id)
                      ? "Sent!"
                      : "Resend"}
                </button>
                <button
                  onClick={() => handleRevoke(inv.id, inv.email)}
                  aria-label={`Delete invite for ${inv.email}`}
                  className="px-2 py-0.5 text-[10px] text-text-muted hover:text-error hover:bg-error/10 rounded transition-colors"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
