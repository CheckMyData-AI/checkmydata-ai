"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { toast } from "@/stores/toast-store";
import { Icon } from "@/components/ui/Icon";
import { LogoMark } from "@/components/ui/Logo";
import { Spinner } from "@/components/ui/Spinner";

const MIN_PASSWORD = 8;

function ResetPasswordContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const passwordTooShort = password.length > 0 && password.length < MIN_PASSWORD;
  const mismatch = confirm.length > 0 && confirm !== password;

  const inputCls =
    "w-full px-3.5 py-2.5 bg-surface-1 text-text-primary rounded-lg text-sm border border-border-subtle focus:border-accent focus:ring-1 focus:ring-accent focus:outline-none transition-colors placeholder-text-muted";

  // No token in the URL — the link is malformed; steer the user to request a fresh one.
  if (!token) {
    return (
      <Shell>
        <div className="flex flex-col items-center gap-3 text-center" aria-live="assertive">
          <span className="flex h-11 w-11 items-center justify-center rounded-full bg-error-muted text-error">
            <Icon name="alert-triangle" size={22} />
          </span>
          <h2 className="text-lg font-semibold text-text-primary">Invalid reset link</h2>
          <p className="text-sm text-text-tertiary">
            This password reset link is missing its token. Request a new one to continue.
          </p>
          <Link
            href="/forgot-password"
            className="mt-2 w-full py-2.5 bg-accent text-white rounded-lg text-sm font-semibold hover:bg-accent-hover transition-colors"
          >
            Request a new link
          </Link>
        </div>
      </Shell>
    );
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password.length < MIN_PASSWORD) {
      setError(`Password must be at least ${MIN_PASSWORD} characters`);
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.auth.resetPassword(token, password);
      toast("Password reset — please sign in with your new password.", "success");
      router.replace("/login");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "This password reset link is invalid or has expired.",
      );
      setSubmitting(false);
    }
  };

  return (
    <Shell>
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <h2 className="text-lg font-semibold text-text-primary">Set a new password</h2>

        <div>
          <input
            type="password"
            placeholder="New password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              if (error) setError(null);
            }}
            required
            minLength={MIN_PASSWORD}
            autoFocus
            className={`${inputCls} ${passwordTooShort ? "border-error focus:border-error focus:ring-error/30" : ""}`}
            aria-label="New password"
            aria-required="true"
            aria-invalid={passwordTooShort || undefined}
          />
          {passwordTooShort ? (
            <p className="text-[10px] text-error mt-1 px-1">
              Password must be at least {MIN_PASSWORD} characters
            </p>
          ) : (
            <p className="text-[10px] text-text-muted mt-1 px-1">
              Min. {MIN_PASSWORD} characters
            </p>
          )}
        </div>

        <div>
          <input
            type="password"
            placeholder="Confirm new password"
            value={confirm}
            onChange={(e) => {
              setConfirm(e.target.value);
              if (error) setError(null);
            }}
            required
            className={`${inputCls} ${mismatch ? "border-error focus:border-error focus:ring-error/30" : ""}`}
            aria-label="Confirm new password"
            aria-required="true"
            aria-invalid={mismatch || undefined}
          />
          {mismatch && (
            <p className="text-[10px] text-error mt-1 px-1">Passwords do not match</p>
          )}
        </div>

        {error && (
          <div className="text-error text-xs flex flex-col gap-1" aria-live="assertive">
            <span className="flex items-center gap-1">
              <Icon name="x" size={12} />
              {error}
            </span>
            <Link
              href="/forgot-password"
              className="text-accent hover:text-accent-hover transition-colors pl-4"
            >
              Request a new reset link
            </Link>
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full py-2.5 bg-accent text-white rounded-lg text-sm font-semibold hover:bg-accent-hover disabled:opacity-50 transition-colors"
        >
          {submitting ? "Resetting…" : "Reset password"}
        </button>

        <p className="text-xs text-center text-text-tertiary">
          <Link
            href="/login"
            className="text-accent hover:text-accent-hover transition-colors"
          >
            Back to sign in
          </Link>
        </p>
      </form>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-surface-0 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <Link href="/" className="inline-block">
            <LogoMark size={48} className="mx-auto mb-4" />
          </Link>
          <h1 className="text-2xl font-bold text-text-primary tracking-tight">
            CheckMyData<span className="text-accent">.ai</span>
          </h1>
        </div>
        <div className="bg-surface-1 rounded-xl p-6 border border-border-subtle">
          {children}
        </div>
      </div>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-surface-0 flex items-center justify-center">
          <Spinner />
        </div>
      }
    >
      <ResetPasswordContent />
    </Suspense>
  );
}
