"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import { toast } from "@/stores/toast-store";

/**
 * Resend the verification link, and say honestly whether it went.
 *
 * The banner and the onboarding wizard both used to toast "Verification email
 * sent — check your inbox" unconditionally, because `POST /api/auth/resend-verification`
 * discarded its own send result. `EmailService._send` returns `false` when no
 * provider is configured and after its retries are spent, so the message was a
 * claim about something nobody had checked — told to the one account type that
 * cannot create anything until the mail arrives.
 *
 * The route now reports `email_sent`, and this button reads it.
 */
export function ResendVerificationButton({ className = "" }: { className?: string }) {
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);

  const handleResend = async () => {
    setSending(true);
    try {
      const res = await api.auth.resendVerification();
      if (res?.already_verified) {
        toast("This address is already verified — reload the page.", "success");
      } else if (res?.email_sent === false) {
        // Measured, not assumed: the provider refused or is not configured.
        toast(
          "We could not send the email — the mail provider rejected it. Contact support and we will verify you by hand.",
          "error",
        );
      } else {
        setDone(true);
        toast("Verification email sent — check your inbox.", "success");
      }
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
    <button
      type="button"
      onClick={handleResend}
      disabled={sending || done}
      className={className}
    >
      {sending ? "Sending…" : done ? "Link sent" : "Resend verification email"}
    </button>
  );
}
