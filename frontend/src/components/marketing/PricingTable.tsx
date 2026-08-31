"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { billing, type BillingPlan } from "@/lib/api/billing";
import { useAuthStore } from "@/stores/auth-store";
import { toast } from "@/stores/toast-store";

/**
 * Shown when the billing API answers nothing — a self-hosted install, or billing off.
 *
 * **Carries no prices.** It used to list free/pro/team at $0/$49/$199, which made this
 * file a second home for numbers that live in the `plans` table and in Stripe. Those
 * three tiers were retired on 2026-08-31 and this block still advertised them, which is
 * exactly how a stale price reaches a customer: nothing fails, the page simply lies.
 *
 * A self-hosted install has no plan to sell, so the honest fallback describes the build
 * rather than quoting a tariff.
 */
const FALLBACK_PLANS: BillingPlan[] = [
  {
    id: "self_hosted",
    name: "Self-hosted",
    description:
      "You are running the open-source build. Every limit is yours to set, and you bring your own LLM key.",
    price_usd_month: 0,
    daily_token_limit: null,
    monthly_token_limit: null,
    max_connections: null,
    max_projects: null,
    // 0 = unlimited, the convention used for every other limit here.
    seats: 0,
    trial_days: 0,
  },
];

function fmtTokens(n: number | null): string {
  if (n == null) return "Unlimited";
  if (n >= 1_000_000) return `${n / 1_000_000}M`;
  if (n >= 1_000) return `${n / 1_000}K`;
  return String(n);
}

function planFeatures(p: BillingPlan): string[] {
  return [
    `${p.max_projects ?? "Unlimited"} project${(p.max_projects ?? 2) === 1 ? "" : "s"}`,
    `${p.max_connections ?? "Unlimited"} database connection${(p.max_connections ?? 2) === 1 ? "" : "s"}`,
    `${fmtTokens(p.monthly_token_limit)} LLM tokens / month`,
    // `0` is unlimited here as it is for every other limit in this codebase. Rendered
    // literally it says "0 seats", which reads as a plan you cannot use — and the
    // self-hosted fallback is exactly the entry that carries it.
    p.seats > 0 ? `${p.seats} seat${p.seats === 1 ? "" : "s"}` : "Unlimited seats",
    ...(p.trial_days > 0 ? [`${p.trial_days}-day free trial`] : []),
  ];
}

export function PricingTable() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const [plans, setPlans] = useState<BillingPlan[]>(FALLBACK_PLANS);
  const [billingLive, setBillingLive] = useState(false);
  const [busyPlan, setBusyPlan] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    billing
      .listPlans()
      .then((res) => {
        if (!cancelled && res.plans.length > 0) {
          setPlans(res.plans);
          setBillingLive(true);
        }
      })
      .catch(() => {
        /* billing disabled — keep the static catalog */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function selectPlan(plan: BillingPlan) {
    if (plan.price_usd_month <= 0) {
      router.push(user ? "/app" : "/login");
      return;
    }
    if (!user) {
      router.push("/login?next=/pricing");
      return;
    }
    if (!billingLive) {
      toast("Billing is not enabled on this deployment", "error");
      return;
    }
    setBusyPlan(plan.id);
    try {
      const { url } = await billing.createCheckout(plan.id);
      window.location.href = url;
    } catch (err) {
      toast(err instanceof Error ? err.message : "Checkout failed", "error");
      setBusyPlan(null);
    }
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-12">
      {plans.map((plan) => {
        const highlighted = plan.id === "pro";
        return (
          <div
            key={plan.id}
            className={`flex flex-col bg-surface-1 rounded-xl border p-6 transition-colors ${
              highlighted ? "border-accent" : "border-border-subtle"
            }`}
          >
            {highlighted && (
              <span className="self-start px-2 py-0.5 mb-3 rounded-full bg-accent/10 text-accent text-meta font-semibold uppercase tracking-wide">
                Most popular
              </span>
            )}
            <h3 className="text-lg font-semibold text-text-primary">{plan.name}</h3>
            <p className="mt-1 text-sm text-text-secondary min-h-10">{plan.description}</p>
            <div className="mt-4 flex items-baseline gap-1">
              <span className="text-4xl font-bold text-text-primary tracking-tight">
                ${plan.price_usd_month}
              </span>
              <span className="text-sm text-text-tertiary">/ month</span>
            </div>
            <ul className="mt-6 space-y-2.5 flex-1">
              {planFeatures(plan).map((f) => (
                <li key={f} className="flex items-start gap-2 text-sm text-text-secondary">
                  <span aria-hidden className="text-accent mt-0.5">
                    ✓
                  </span>
                  {f}
                </li>
              ))}
            </ul>
            <button
              type="button"
              onClick={() => selectPlan(plan)}
              disabled={busyPlan !== null}
              aria-label={`Choose the ${plan.name} plan`}
              className={`mt-8 w-full px-4 py-2.5 text-sm font-semibold rounded-lg transition-colors disabled:opacity-60 disabled:cursor-not-allowed ${
                highlighted
                  ? "text-primary-foreground bg-primary hover:bg-primary/92"
                  : "text-text-primary border border-border-default hover:border-accent hover:text-accent"
              }`}
            >
              {busyPlan === plan.id
                ? "Redirecting…"
                : plan.price_usd_month <= 0
                  ? "Get started free"
                  : plan.trial_days > 0
                    ? `Start ${plan.trial_days}-day trial`
                    : `Choose ${plan.name}`}
            </button>
          </div>
        );
      })}
    </div>
  );
}
