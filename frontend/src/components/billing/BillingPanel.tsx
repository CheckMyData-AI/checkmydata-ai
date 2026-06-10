"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { billing, type BillingSubscription } from "@/lib/api/billing";
import { toast } from "@/stores/toast-store";

function fmt(n: number | null): string {
  if (n == null) return "∞";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function UsageBar({
  label,
  used,
  limit,
}: {
  label: string;
  used: number | null;
  limit: number | null;
}) {
  const pct =
    used != null && limit != null && limit > 0
      ? Math.min((used / limit) * 100, 100)
      : 0;
  const nearLimit = pct >= 80;
  return (
    <div>
      <div className="flex items-center justify-between text-[11px] text-text-tertiary">
        <span>{label}</span>
        <span className="font-mono">
          {fmt(used)} / {fmt(limit)}
        </span>
      </div>
      <div
        className="mt-1 h-1.5 rounded-full bg-surface-2 overflow-hidden"
        role="progressbar"
        aria-label={`${label} token usage`}
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={`h-full rounded-full transition-all duration-150 ${
            nearLimit ? "bg-warning" : "bg-accent/70"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

const STATUS_LABEL: Record<string, string> = {
  free: "Free",
  trialing: "Trial",
  active: "Active",
  past_due: "Past due",
  canceled: "Canceled",
};

/**
 * Current plan + usage vs plan limits, with upgrade / manage-billing actions.
 * Renders nothing when billing is disabled on the deployment (API 404s).
 */
export function BillingPanel() {
  const [sub, setSub] = useState<BillingSubscription | null>(null);
  const [portalBusy, setPortalBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    billing
      .getSubscription()
      .then((res) => {
        if (!cancelled) setSub(res);
      })
      .catch(() => {
        /* billing disabled — render nothing */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!sub) return null;

  const ent = sub.entitlements;
  const isPaid = ent.plan_id !== "free" && ["active", "trialing", "past_due"].includes(ent.status);

  async function openPortal() {
    setPortalBusy(true);
    try {
      const { url } = await billing.createPortal();
      window.location.href = url;
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not open billing portal", "error");
      setPortalBusy(false);
    }
  }

  return (
    <div className="px-2 py-2 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-text-primary">{ent.plan_name} plan</span>
          <span
            role="status"
            className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
              ent.status === "past_due"
                ? "bg-warning/10 text-warning"
                : ent.status === "canceled"
                  ? "bg-surface-2 text-text-tertiary"
                  : "bg-accent/10 text-accent"
            }`}
          >
            {STATUS_LABEL[ent.status] ?? ent.status}
          </span>
        </div>
      </div>

      {ent.status === "past_due" && (
        <p className="text-[11px] text-warning leading-snug">
          Your last payment failed — update your card to keep your plan.
        </p>
      )}
      {ent.cancel_at_period_end && ent.current_period_end && (
        <p className="text-[11px] text-text-tertiary leading-snug">
          Cancels on {new Date(ent.current_period_end).toLocaleDateString()}.
        </p>
      )}

      <div className="space-y-2">
        <UsageBar label="Today" used={sub.usage.daily_used} limit={sub.usage.daily_limit} />
        <UsageBar
          label="This month"
          used={sub.usage.monthly_used}
          limit={sub.usage.monthly_limit}
        />
      </div>

      <div className="flex items-center gap-2">
        {isPaid ? (
          <button
            type="button"
            onClick={openPortal}
            disabled={portalBusy}
            className="flex-1 px-2.5 py-1.5 text-[11px] font-semibold text-text-primary border border-border-default hover:border-accent hover:text-accent rounded-lg transition-colors disabled:opacity-60"
          >
            {portalBusy ? "Opening…" : "Manage billing"}
          </button>
        ) : (
          <Link
            href="/pricing"
            className="flex-1 px-2.5 py-1.5 text-[11px] font-semibold text-center text-white bg-accent hover:bg-accent-hover rounded-lg transition-colors"
          >
            Upgrade
          </Link>
        )}
      </div>
    </div>
  );
}
