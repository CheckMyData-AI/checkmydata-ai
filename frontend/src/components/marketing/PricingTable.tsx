"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { billing, type BillingPlan } from "@/lib/api/billing";
import { useAuthStore } from "@/stores/auth-store";
import { toast } from "@/stores/toast-store";

/** Static catalog shown when the billing API is disabled (self-hosted mode). */
const FALLBACK_PLANS: BillingPlan[] = [
  {
    id: "free",
    name: "Free",
    description: "Try CheckMyData on a single project.",
    price_usd_month: 0,
    daily_token_limit: 100_000,
    monthly_token_limit: 1_000_000,
    max_connections: 1,
    max_projects: 1,
    seats: 1,
    trial_days: 0,
  },
  {
    id: "pro",
    name: "Pro",
    description: "For individual analysts and small teams.",
    price_usd_month: 49,
    daily_token_limit: 1_000_000,
    monthly_token_limit: 15_000_000,
    max_connections: 5,
    max_projects: 5,
    seats: 3,
    trial_days: 14,
  },
  {
    id: "team",
    name: "Team",
    description: "For data teams that need scale and collaboration.",
    price_usd_month: 199,
    daily_token_limit: 5_000_000,
    monthly_token_limit: 75_000_000,
    max_connections: 25,
    max_projects: 25,
    seats: 10,
    trial_days: 14,
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
    `${p.seats} seat${p.seats === 1 ? "" : "s"}`,
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
              <span className="self-start px-2 py-0.5 mb-3 rounded-full bg-accent/10 text-accent text-[11px] font-semibold uppercase tracking-wide">
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
                  ? "text-white bg-accent hover:bg-accent-hover"
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
