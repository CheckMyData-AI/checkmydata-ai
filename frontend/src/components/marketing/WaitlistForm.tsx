"use client";

import { useState } from "react";
import { WAITLIST_LIMITS } from "@/lib/waitlist";

type Status =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "done" }
  | { kind: "error"; message: string; field?: string };

const inputCls =
  "w-full px-3.5 py-2.5 bg-surface-1 text-text-primary rounded-lg text-sm border border-border-subtle focus:border-accent focus:ring-1 focus:ring-accent focus:outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring transition-colors placeholder-text-muted";

/**
 * The site's only call to action since the hosted product was switched off
 * (2026-10-11). Posts to /api/waitlist, which mails contact@checkmydata.ai.
 */
export function WaitlistForm() {
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setStatus({ kind: "sending" });
    try {
      const res = await fetch("/api/waitlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.fromEntries(form.entries())),
      });
      const data = (await res.json().catch(() => ({}))) as { ok?: boolean; error?: string; field?: string };
      if (res.ok && data.ok) {
        setStatus({ kind: "done" });
        return;
      }
      setStatus({
        kind: "error",
        message: data.error || "Something went wrong. Email contact@checkmydata.ai instead.",
        field: data.field,
      });
    } catch {
      setStatus({
        kind: "error",
        message: "No connection. Check your network and try again.",
      });
    }
  }

  if (status.kind === "done") {
    return (
      <div role="status" className="rounded-xl border border-border-subtle bg-surface-1 px-6 py-8 text-center">
        <p className="text-base font-semibold text-text-primary">You&apos;re on the list.</p>
        <p className="mt-2 text-sm text-text-secondary">
          We&apos;ll email you when there&apos;s a spot. Questions in the meantime:{" "}
          <a
            href="mailto:contact@checkmydata.ai"
            className="text-accent hover:text-accent-hover underline underline-offset-2"
          >
            contact@checkmydata.ai
          </a>
          .
        </p>
      </div>
    );
  }

  const sending = status.kind === "sending";
  const emailInvalid = status.kind === "error" && status.field === "email";

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-3 text-left" aria-label="Join the waitlist">
      <div className="grid gap-3 sm:grid-cols-2">
        <input
          type="email"
          name="email"
          placeholder="Work email"
          autoComplete="email"
          required
          maxLength={WAITLIST_LIMITS.email}
          className={`${inputCls} sm:col-span-2 ${emailInvalid ? "border-error focus:border-error focus:ring-error/30" : ""}`}
          aria-label="Work email"
          aria-required="true"
          aria-invalid={emailInvalid}
          aria-describedby={status.kind === "error" ? "waitlist-error" : undefined}
        />
        <input
          type="text"
          name="name"
          placeholder="Name (optional)"
          autoComplete="name"
          maxLength={WAITLIST_LIMITS.name}
          className={inputCls}
          aria-label="Name"
        />
        <input
          type="text"
          name="company"
          placeholder="Company (optional)"
          autoComplete="organization"
          maxLength={WAITLIST_LIMITS.company}
          className={inputCls}
          aria-label="Company"
        />
        <textarea
          name="note"
          rows={3}
          placeholder="What would you ask your database? (optional)"
          maxLength={WAITLIST_LIMITS.note}
          className={`${inputCls} sm:col-span-2 resize-y`}
          aria-label="What would you ask your database?"
        />
      </div>
      {/* Honeypot — hidden from people and from assistive tech. */}
      <div aria-hidden="true" className="hidden">
        <label>
          Website
          <input type="text" name="website" tabIndex={-1} autoComplete="off" />
        </label>
      </div>
      {status.kind === "error" && (
        <p id="waitlist-error" role="alert" className="text-sm text-error">
          {status.message}
        </p>
      )}
      <button
        type="submit"
        disabled={sending}
        className="w-full px-8 py-3.5 text-sm font-semibold text-primary-foreground bg-primary hover:bg-primary/92 rounded-lg transition-colors disabled:opacity-60"
      >
        {sending ? "Joining…" : "Join the waitlist"}
      </button>
      <p className="text-xs text-text-tertiary text-center">
        One email when your spot opens. No newsletter.
      </p>
    </form>
  );
}
