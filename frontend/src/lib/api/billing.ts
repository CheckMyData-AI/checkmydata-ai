import { request } from "./_client";

export interface BillingPlan {
  id: string;
  name: string;
  description: string;
  price_usd_month: number;
  daily_token_limit: number | null;
  monthly_token_limit: number | null;
  max_connections: number | null;
  max_projects: number | null;
  seats: number;
  trial_days: number;
}

export interface BillingEntitlements {
  plan_id: string;
  plan_name: string;
  status: string;
  daily_token_limit: number | null;
  monthly_token_limit: number | null;
  max_connections: number | null;
  max_projects: number | null;
  seats: number;
  cancel_at_period_end: boolean;
  current_period_end: string | null;
}

export interface BillingSubscription {
  entitlements: BillingEntitlements;
  usage: {
    daily_used: number | null;
    monthly_used: number | null;
    daily_limit: number | null;
    monthly_limit: number | null;
  };
}

export const billing = {
  listPlans: () => request<{ plans: BillingPlan[] }>("/billing/plans"),

  getSubscription: () => request<BillingSubscription>("/billing/subscription"),

  /** Start Stripe Checkout for a plan; resolves to the redirect URL. */
  createCheckout: (planId: string) =>
    request<{ url: string }>("/billing/checkout", {
      method: "POST",
      body: JSON.stringify({ plan_id: planId }),
    }),

  /** Open the Stripe Customer Portal; resolves to the redirect URL. */
  createPortal: () =>
    request<{ url: string }>("/billing/portal", { method: "POST" }),
};
