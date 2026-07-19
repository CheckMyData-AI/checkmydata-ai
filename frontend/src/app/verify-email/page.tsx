"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";
import { toast } from "@/stores/toast-store";
import { Icon } from "@/components/ui/Icon";
import { LogoMark } from "@/components/ui/Logo";
import { Spinner } from "@/components/ui/Spinner";

type Status = "loading" | "success" | "error";

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const user = useAuthStore((s) => s.user);
  const [status, setStatus] = useState<Status>("loading");
  const [resending, setResending] = useState(false);
  const [resent, setResent] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!token) {
      setStatus("error");
      return;
    }
    api.auth
      .verifyEmail(token)
      .then(() => {
        if (cancelled) return;
        setStatus("success");
        // Reflect the new state in the cached profile so the app-shell prompt
        // (EmailVerifyBanner) disappears immediately for a logged-in user.
        const current = useAuthStore.getState().user;
        if (current) {
          useAuthStore.setState({ user: { ...current, email_verified: true } });
        }
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const handleResend = async () => {
    setResending(true);
    try {
      await api.auth.resendVerification();
      setResent(true);
      toast("Verification email sent — check your inbox.", "success");
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Could not send verification email.",
        "error",
      );
    } finally {
      setResending(false);
    }
  };

  return (
    <div className="min-h-screen bg-surface-0 flex items-center justify-center p-4">
      <div className="w-full max-w-sm text-center">
        <Link href="/" className="inline-block">
          <LogoMark size={48} className="mx-auto mb-6" />
        </Link>

        <div className="bg-surface-1 rounded-xl p-6 border border-border-subtle">
          {status === "loading" && (
            <div className="flex flex-col items-center gap-3 py-4" aria-live="polite">
              <Spinner />
              <p className="text-sm text-text-tertiary">Verifying your email…</p>
            </div>
          )}

          {status === "success" && (
            <div className="flex flex-col items-center gap-3" aria-live="polite">
              <span className="flex h-11 w-11 items-center justify-center rounded-full bg-success-muted text-success">
                <Icon name="check" size={22} />
              </span>
              <h1 className="text-lg font-semibold text-text-primary">
                Email verified
              </h1>
              <p className="text-sm text-text-tertiary">
                Your email address is confirmed. Any pending project invitations
                have been accepted.
              </p>
              <Link
                href="/app"
                className="mt-2 w-full py-2.5 bg-accent text-white rounded-lg text-sm font-semibold hover:bg-accent-hover transition-colors"
              >
                Continue to app
              </Link>
            </div>
          )}

          {status === "error" && (
            <div className="flex flex-col items-center gap-3" aria-live="assertive">
              <span className="flex h-11 w-11 items-center justify-center rounded-full bg-error-muted text-error">
                <Icon name="alert-triangle" size={22} />
              </span>
              <h1 className="text-lg font-semibold text-text-primary">
                Verification failed
              </h1>
              <p className="text-sm text-text-tertiary">
                This verification link is invalid or has expired.
                {user
                  ? " Request a fresh link below."
                  : " Sign in and resend the link from the app."}
              </p>
              {user && (
                <button
                  type="button"
                  onClick={handleResend}
                  disabled={resending || resent}
                  aria-label="Resend verification email"
                  className="mt-2 w-full py-2.5 bg-accent text-white rounded-lg text-sm font-semibold hover:bg-accent-hover disabled:opacity-50 transition-colors"
                >
                  {resent
                    ? "Email sent"
                    : resending
                      ? "Sending…"
                      : "Resend verification email"}
                </button>
              )}
              <Link
                href={user ? "/app" : "/login"}
                className="text-xs text-accent hover:text-accent-hover transition-colors"
              >
                {user ? "Back to app" : "Back to sign in"}
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-surface-0 flex items-center justify-center">
          <Spinner />
        </div>
      }
    >
      <VerifyEmailContent />
    </Suspense>
  );
}
