"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { Icon } from "@/components/ui/Icon";
import { LogoMark } from "@/components/ui/Logo";

type Status = "idle" | "loading" | "success" | "error";

const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [emailTouched, setEmailTouched] = useState(false);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);

  const emailInvalid = emailTouched && email.length > 0 && !emailRegex.test(email);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!emailRegex.test(email)) {
      setEmailTouched(true);
      setError("Please enter a valid email address");
      return;
    }
    setStatus("loading");
    setError(null);
    try {
      // The backend always returns a generic ok (no account-existence leak), so a
      // resolved promise is the only signal we act on.
      await api.auth.forgotPassword(email.trim());
      setStatus("success");
    } catch (err) {
      setStatus("error");
      setError(
        err instanceof Error
          ? err.message
          : "Something went wrong. Please try again.",
      );
    }
  };

  const inputCls =
    "w-full px-3.5 py-2.5 bg-surface-1 text-text-primary rounded-lg text-sm border border-border-subtle focus:border-accent focus:ring-1 focus:ring-accent focus:outline-none transition-colors placeholder-text-muted";

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
          {status === "success" ? (
            <div
              className="flex flex-col items-center gap-3 text-center"
              aria-live="polite"
            >
              <span className="flex h-11 w-11 items-center justify-center rounded-full bg-success-muted text-success">
                <Icon name="check" size={22} />
              </span>
              <h2 className="text-lg font-semibold text-text-primary">
                Check your email
              </h2>
              <p className="text-sm text-text-tertiary">
                If an account exists for that address, we&rsquo;ve sent a link to
                reset your password. The link expires in one hour.
              </p>
              <Link
                href="/login"
                className="mt-2 text-xs text-accent hover:text-accent-hover transition-colors"
              >
                Back to sign in
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4" noValidate>
              <h2 className="text-lg font-semibold text-text-primary">
                Reset your password
              </h2>
              <p className="text-sm text-text-tertiary">
                Enter the email associated with your account and we&rsquo;ll send
                you a link to set a new password.
              </p>

              <div>
                <input
                  type="email"
                  placeholder="Email"
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value);
                    if (error) setError(null);
                  }}
                  onBlur={() => setEmailTouched(true)}
                  required
                  autoFocus
                  className={`${inputCls} ${emailInvalid ? "border-error focus:border-error focus:ring-error/30" : ""}`}
                  aria-label="Email"
                  aria-required="true"
                  aria-invalid={emailInvalid || undefined}
                />
                {emailInvalid && (
                  <p className="text-[10px] text-error mt-1 px-1">
                    Please enter a valid email address
                  </p>
                )}
              </div>

              {error && !emailInvalid && (
                <p className="text-error text-xs flex items-center gap-1" aria-live="assertive">
                  <Icon name="x" size={12} />
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={status === "loading"}
                className="w-full py-2.5 bg-accent text-white rounded-lg text-sm font-semibold hover:bg-accent-hover disabled:opacity-50 transition-colors"
              >
                {status === "loading" ? "Sending…" : "Send reset link"}
              </button>

              <p className="text-xs text-center text-text-tertiary">
                Remembered it?{" "}
                <Link
                  href="/login"
                  className="text-accent hover:text-accent-hover transition-colors"
                >
                  Back to sign in
                </Link>
              </p>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
