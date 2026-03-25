"use client";

import { useState, useRef, useEffect } from "react";
import { api } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";
import { toast } from "@/stores/toast-store";
import { Icon } from "@/components/ui/Icon";
import { PopoverPortal } from "@/components/ui/PopoverPortal";

type View = "menu" | "password" | "delete";

export function AccountMenu() {
  const logout = useAuthStore((s) => s.logout);
  const user = useAuthStore((s) => s.user);
  const isGoogleOnly = user?.auth_provider === "google";
  const [view, setView] = useState<View>("menu");
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        triggerRef.current?.contains(target) ||
        panelRef.current?.contains(target)
      ) return;
      setOpen(false);
      setView("menu");
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        setView("menu");
      }
    };
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  return (
    <>
      <button
        ref={triggerRef}
        onClick={() => setOpen((v) => !v)}
        className="p-1 rounded text-text-muted hover:text-text-secondary hover:bg-surface-2 transition-colors shrink-0"
        title="Account settings"
        aria-label="Account settings"
      >
        <Icon name="settings" size={14} />
      </button>

      {open && (
        <PopoverPortal triggerRef={triggerRef} placement="top-left" gap={8}>
          <div
            ref={panelRef}
            className="w-56 bg-surface-1 border border-border-subtle rounded-lg shadow-xl animate-fade-in"
          >
            {view === "menu" && (
              <div className="py-1">
                {!isGoogleOnly && (
                  <button
                    onClick={() => setView("password")}
                    className="w-full flex items-center gap-2.5 px-3 py-2 text-xs text-text-secondary hover:bg-surface-2 transition-colors"
                  >
                    <Icon name="lock" size={12} />
                    Change Password
                  </button>
                )}
                <button
                  onClick={logout}
                  className="w-full flex items-center gap-2.5 px-3 py-2 text-xs text-text-secondary hover:bg-surface-2 transition-colors"
                >
                  <Icon name="log-out" size={12} />
                  Sign Out
                </button>
                <div className="border-t border-border-subtle my-1" />
                <button
                  onClick={() => setView("delete")}
                  className="w-full flex items-center gap-2.5 px-3 py-2 text-xs text-error hover:bg-error/10 transition-colors"
                >
                  <Icon name="trash" size={12} />
                  Delete Account
                </button>
              </div>
            )}

            {view === "password" && <PasswordForm onClose={() => { setView("menu"); setOpen(false); }} />}
            {view === "delete" && <DeleteConfirm onClose={() => { setView("menu"); setOpen(false); }} />}
          </div>
        </PopoverPortal>
      )}
    </>
  );
}

function PasswordForm({ onClose }: { onClose: () => void }) {
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
      onClose();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to change password", "error");
    } finally {
      setLoading(false);
    }
  };

  const inputCls =
    "w-full px-2.5 py-1.5 bg-surface-0 text-text-primary rounded text-xs border border-border-subtle focus:border-accent focus:ring-1 focus:ring-accent focus:outline-none transition-colors placeholder-text-muted";

  return (
    <form onSubmit={handleSubmit} className="p-3 space-y-2.5">
      <p className="text-xs font-medium text-text-primary">Change Password</p>
      <input
        type="password"
        placeholder="Current password"
        value={current}
        onChange={(e) => setCurrent(e.target.value)}
        required
        aria-required="true"
        className={inputCls}
        aria-label="Current password"
      />
      <input
        type="password"
        placeholder="New password (min 8 chars)"
        value={next}
        onChange={(e) => setNext(e.target.value)}
        required
        aria-required="true"
        minLength={8}
        className={inputCls}
        aria-label="New password"
      />
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onClose}
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

function DeleteConfirm({ onClose }: { onClose: () => void }) {
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
    <div className="p-3 space-y-2.5">
      <p className="text-xs font-medium text-error">Delete Account</p>
      <p className="text-[11px] text-text-secondary leading-relaxed">
        This will permanently delete your account and all associated data. This action cannot be undone.
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
          onClick={onClose}
          className="flex-1 py-1.5 text-xs text-text-secondary bg-surface-2 rounded hover:bg-surface-3 transition-colors"
        >
          Cancel
        </button>
        <button
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
