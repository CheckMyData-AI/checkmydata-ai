"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";
import { toast } from "@/stores/toast-store";
import { Icon } from "@/components/ui/Icon";

/**
 * Unobtrusive app-shell banner prompting an unverified email/password user to
 * verify their address (SCN-012, F-PROJ-01). Hidden for verified users and for
 * Google accounts (pre-verified). Offers a one-click "Resend email" action.
 */
export function EmailVerifyBanner() {
  const user = useAuthStore((s) => s.user);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);

  // Only nag when we positively know the address is unverified. `email_verified`
  // is optional (undefined on cached pre-field profiles) — undefined !== false,
  // so the banner stays hidden until a fresh profile confirms it's unverified.
  if (!user || user.email_verified !== false || user.auth_provider === "google") {
    return null;
  }

  const handleResend = async () => {
    setSending(true);
    try {
      await api.auth.resendVerification();
      setSent(true);
      toast("Verification email sent — check your inbox.", "success");
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Could not send verification email.",
        "error",
      );
    } finally {
      setSending(false);
    }
  };

  return (
    <div
      role="status"
      className="flex items-center gap-3 border-b border-warning/20 bg-warning/10 px-4 py-2 text-xs text-text-secondary"
    >
      <Icon name="alert-triangle" size={14} className="shrink-0 text-warning" />
      <span className="min-w-0 flex-1">
        Verify your email address to secure your account and receive pending
        project invitations.
      </span>
      <button
        type="button"
        onClick={handleResend}
        disabled={sending || sent}
        aria-label="Resend verification email"
        className="shrink-0 rounded-md border border-border-subtle bg-surface-1 px-2.5 py-1 text-xs font-medium text-text-primary transition-colors hover:bg-surface-2 disabled:opacity-50 outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        {sent ? "Email sent" : sending ? "Sending…" : "Resend email"}
      </button>
    </div>
  );
}
