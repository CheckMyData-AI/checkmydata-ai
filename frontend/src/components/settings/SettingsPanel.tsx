"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";
import { useAppStore } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";
import { Icon } from "@/components/ui/Icon";
import { InviteManager } from "@/components/projects/InviteManager";
import { McpTokenManager } from "@/components/mcp/McpTokenManager";
import { usePermission } from "@/hooks/usePermission";
import type { AppPanel } from "@/hooks/useAppPanel";

interface SettingsPanelProps {
  onClose?: () => void;
  onNavigate?: (panel: AppPanel) => void;
}

export function SettingsPanel({ onClose, onNavigate }: SettingsPanelProps) {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const activeProject = useAppStore((s) => s.activeProject);
  const setFocusSection = useAppStore((s) => s.setFocusSidebarSection);
  const { isOwner } = usePermission();
  const isGoogleOnly = user?.auth_provider === "google";

  const [showPassword, setShowPassword] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [showInvites, setShowInvites] = useState(false);

  const openProjectSettings = () => {
    setFocusSection("projects");
    onClose?.();
  };

  const openConnections = () => {
    setFocusSection("connections");
    onNavigate?.("connections");
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-lg mx-auto p-6 space-y-6">
        <div className="flex items-center gap-3">
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close settings"
              className="p-1.5 rounded-md hover:bg-surface-2 transition-colors text-text-muted"
            >
              <Icon name="arrow-left" size={16} />
            </button>
          )}
          <div>
            <h2 className="text-sm font-semibold text-text-primary">Settings</h2>
            <p className="text-xs text-text-tertiary">Account and project preferences</p>
          </div>
        </div>

        {user && (
          <section className="rounded-lg border border-border-subtle bg-surface-1/50 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-border-subtle">
              <h3 className="text-xs font-medium text-text-secondary uppercase tracking-wider">
                Account
              </h3>
            </div>
            <div className="px-4 py-3 flex items-center gap-3 border-b border-border-subtle">
              {user.picture_url ? (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img
                  src={user.picture_url}
                  alt=""
                  referrerPolicy="no-referrer"
                  className="w-9 h-9 rounded-full border border-border-default object-cover"
                />
              ) : (
                <div className="w-9 h-9 rounded-full bg-surface-2 border border-border-default flex items-center justify-center">
                  <Icon name="users" size={16} className="text-text-secondary" />
                </div>
              )}
              <div className="min-w-0">
                <p className="text-sm text-text-primary truncate">
                  {user.display_name || user.email?.split("@")[0]}
                </p>
                <p className="text-xs text-text-muted truncate">{user.email}</p>
              </div>
            </div>
            <div className="py-1">
              {!isGoogleOnly && (
                <button
                  type="button"
                  onClick={() => {
                    setShowPassword((v) => !v);
                    setShowDelete(false);
                  }}
                  className="w-full flex items-center gap-2.5 px-4 py-2.5 text-xs text-text-secondary hover:bg-surface-2 transition-colors text-left"
                >
                  <Icon name="lock" size={14} className="text-text-tertiary" />
                  Change Password
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  logout();
                  toast("Signed out", "success");
                }}
                className="w-full flex items-center gap-2.5 px-4 py-2.5 text-xs text-text-secondary hover:bg-surface-2 transition-colors text-left"
              >
                <Icon name="log-out" size={14} className="text-text-tertiary" />
                Sign Out
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowDelete((v) => !v);
                  setShowPassword(false);
                }}
                className="w-full flex items-center gap-2.5 px-4 py-2.5 text-xs text-error hover:bg-error/10 transition-colors text-left"
              >
                <Icon name="trash" size={14} />
                Delete Account
              </button>
            </div>
            {showPassword && !isGoogleOnly && <PasswordForm onDone={() => setShowPassword(false)} />}
            {showDelete && <DeleteConfirm onDone={() => setShowDelete(false)} />}
          </section>
        )}

        {activeProject && (
          <section className="rounded-lg border border-border-subtle bg-surface-1/50 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-border-subtle">
              <h3 className="text-xs font-medium text-text-secondary uppercase tracking-wider">
                Project
              </h3>
            </div>
            <div className="px-4 py-3 border-b border-border-subtle">
              <p className="text-sm text-text-primary">{activeProject.name}</p>
              {activeProject.repo_url && (
                <p className="text-[11px] text-text-muted font-mono truncate mt-0.5">
                  {activeProject.repo_url}
                </p>
              )}
            </div>
            <div className="py-1">
              <button
                type="button"
                onClick={openProjectSettings}
                className="w-full flex items-center gap-2.5 px-4 py-2.5 text-xs text-text-secondary hover:bg-surface-2 transition-colors text-left"
              >
                <Icon name="folder-git" size={14} className="text-text-tertiary" />
                Edit Project
              </button>
              <button
                type="button"
                onClick={openConnections}
                className="w-full flex items-center gap-2.5 px-4 py-2.5 text-xs text-text-secondary hover:bg-surface-2 transition-colors text-left"
              >
                <Icon name="database" size={14} className="text-text-tertiary" />
                Manage Connections
              </button>
              {isOwner && (
                <button
                  type="button"
                  onClick={() => setShowInvites((v) => !v)}
                  className="w-full flex items-center gap-2.5 px-4 py-2.5 text-xs text-text-secondary hover:bg-surface-2 transition-colors text-left"
                >
                  <Icon name="users" size={14} className="text-text-tertiary" />
                  Team & Invites
                </button>
              )}
            </div>
            {showInvites && isOwner && activeProject && (
              <div className="border-t border-border-subtle p-3">
                <InviteManager projectId={activeProject.id} onClose={() => setShowInvites(false)} />
              </div>
            )}
          </section>
        )}

        <McpTokenManager />

        <div className="flex items-center gap-3 text-xs text-text-muted px-1">
          <Link href="/terms" className="hover:text-text-secondary transition-colors">
            Terms
          </Link>
          <span className="text-text-muted/40">&middot;</span>
          <Link href="/privacy" className="hover:text-text-secondary transition-colors">
            Privacy
          </Link>
        </div>
      </div>
    </div>
  );
}

function PasswordForm({ onDone }: { onDone: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (next.length < 8) {
      toast("New password must be at least 8 characters", "error");
      return;
    }
    setLoading(true);
    try {
      await api.auth.changePassword(current, next);
      toast("Password changed successfully", "success");
      onDone();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to change password", "error");
    } finally {
      setLoading(false);
    }
  };

  const inputCls =
    "w-full px-2.5 py-1.5 bg-surface-0 text-text-primary rounded text-xs border border-border-subtle focus:border-accent focus:ring-1 focus:ring-accent focus:outline-none transition-colors placeholder-text-muted";

  return (
    <form onSubmit={handleSubmit} className="px-4 pb-4 space-y-2.5 border-t border-border-subtle pt-3">
      <input
        type="password"
        placeholder="Current password"
        value={current}
        onChange={(e) => setCurrent(e.target.value)}
        required
        className={inputCls}
        aria-label="Current password"
      />
      <input
        type="password"
        placeholder="New password (min 8 chars)"
        value={next}
        onChange={(e) => setNext(e.target.value)}
        required
        minLength={8}
        className={inputCls}
        aria-label="New password"
      />
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onDone}
          className="flex-1 py-1.5 text-xs text-text-secondary bg-surface-2 rounded hover:bg-surface-3 transition-colors"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={loading}
          className="flex-1 py-1.5 text-xs text-white bg-accent rounded hover:bg-accent-hover disabled:opacity-50 transition-colors"
        >
          {loading ? "Saving..." : "Save"}
        </button>
      </div>
    </form>
  );
}

function DeleteConfirm({ onDone }: { onDone: () => void }) {
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const logout = useAuthStore((s) => s.logout);

  const handleDelete = async () => {
    setLoading(true);
    try {
      await api.auth.deleteAccount();
      toast("Account deleted", "success");
      logout();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to delete account", "error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="px-4 pb-4 space-y-2.5 border-t border-border-subtle pt-3">
      <p className="text-[11px] text-text-secondary leading-relaxed">
        This will permanently delete your account and all associated data.
      </p>
      <input
        type="text"
        placeholder='Type "DELETE" to confirm'
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
        className="w-full px-2.5 py-1.5 bg-surface-0 text-text-primary rounded text-xs border border-border-subtle focus:border-error focus:ring-1 focus:ring-error focus:outline-none transition-colors placeholder-text-muted"
        aria-label="Confirm deletion"
      />
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onDone}
          className="flex-1 py-1.5 text-xs text-text-secondary bg-surface-2 rounded hover:bg-surface-3 transition-colors"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleDelete}
          disabled={confirm !== "DELETE" || loading}
          className="flex-1 py-1.5 text-xs text-white bg-error rounded hover:bg-error/90 disabled:opacity-50 transition-colors"
        >
          {loading ? "Deleting..." : "Delete"}
        </button>
      </div>
    </div>
  );
}
