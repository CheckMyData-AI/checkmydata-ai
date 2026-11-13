/**
 * The site's Cloudflare Worker (2026-10-12).
 *
 * checkmydata.ai is a static export served from Workers Static Assets: no server, no
 * database, no monthly cost. The one dynamic thing it does is the waitlist, so the
 * Worker runs first only for `/api/*` (see `wrangler.jsonc`) and hands every other
 * request straight to the assets, which apply `public/_headers` and `public/_redirects`.
 *
 * POST /api/waitlist mails one sign-up to contact@checkmydata.ai through Cloudflare Email
 * Sending, with the visitor as Reply-To. contact@ routes to Fabric Inbox (Email Routing), so
 * every sign-up lands in Fabric. Resend did this until 2026-11-13, when the operator retired it
 * everywhere. The sender is on `mail.checkmydata.ai`, a subdomain onboarded for sending:
 * Cloudflare refuses to send from a domain to an address on that same domain (10203).
 *
 * A sign-up that could not be mailed is reported to the visitor as a failure: it is never
 * acknowledged and then dropped. The inbox is the record.
 */
import { parseWaitlist, waitlistEmail } from "../src/lib/waitlist";

export interface Env {
  ASSETS: { fetch(request: Request): Promise<Response> };
  /** Cloudflare Rate Limiting binding; absent in local tests, where nothing is limited. */
  WAITLIST_LIMITER?: { limit(options: { key: string }): Promise<{ success: boolean }> };
  /** A token that can only send from the account (Observatory preset `email-send`), a Worker secret. */
  CLOUDFLARE_EMAIL_API_TOKEN?: string;
  CLOUDFLARE_EMAIL_ACCOUNT_ID?: string;
  WAITLIST_TO?: string;
  WAITLIST_FROM?: string;
}

const API = "https://api.cloudflare.com/client/v4";
const DEFAULT_TO = "contact@checkmydata.ai";
const DEFAULT_FROM = { address: "noreply@mail.checkmydata.ai", name: "CheckMyData" };
const UNSAVED = "We couldn't save your sign-up. Try again, or email contact@checkmydata.ai.";

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store", ...headers },
  });
}

/** Structured, and without the visitor's address: the inbox holds that, the log does not. */
function log(event: string, fields: Record<string, unknown> = {}): void {
  console.log(JSON.stringify({ at: new Date().toISOString(), scope: "waitlist", event, ...fields }));
}

export async function handleWaitlist(request: Request, env: Env): Promise<Response> {
  if (request.method !== "POST") {
    return json({ ok: false, error: "Use POST." }, 405, { Allow: "POST" });
  }

  if (env.WAITLIST_LIMITER) {
    const key = request.headers.get("CF-Connecting-IP") ?? "unknown";
    const { success } = await env.WAITLIST_LIMITER.limit({ key });
    if (!success) {
      log("rate_limited");
      return json({ ok: false, error: "Too many sign-ups from here. Try again in a minute." }, 429);
    }
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return json({ ok: false, error: "Send the form as JSON." }, 400);
  }

  const parsed = parseWaitlist(body);
  if (!parsed.ok) {
    if (parsed.reason === "bot") {
      log("honeypot");
      return json({ ok: true });
    }
    return json({ ok: false, field: parsed.field, error: parsed.message }, 422);
  }

  if (!env.CLOUDFLARE_EMAIL_API_TOKEN || !env.CLOUDFLARE_EMAIL_ACCOUNT_ID) {
    log("not_configured", { missing: !env.CLOUDFLARE_EMAIL_API_TOKEN ? "CLOUDFLARE_EMAIL_API_TOKEN" : "CLOUDFLARE_EMAIL_ACCOUNT_ID" });
    return json(
      { ok: false, error: "Sign-ups are briefly unavailable. Email contact@checkmydata.ai instead." },
      503,
    );
  }

  const { subject, text } = waitlistEmail(parsed.entry);
  try {
    const res = await fetch(`${API}/accounts/${env.CLOUDFLARE_EMAIL_ACCOUNT_ID}/email/sending/send`, {
      method: "POST",
      headers: { Authorization: `Bearer ${env.CLOUDFLARE_EMAIL_API_TOKEN}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        from: env.WAITLIST_FROM ? { address: env.WAITLIST_FROM } : DEFAULT_FROM,
        to: [env.WAITLIST_TO || DEFAULT_TO],
        reply_to: { address: parsed.entry.email },
        subject,
        text,
      }),
      signal: AbortSignal.timeout(10_000),
    });
    const sent = (await res.json().catch(() => ({}))) as {
      success?: boolean;
      errors?: { code?: number; message?: string }[];
      result?: { message_id?: string } | null;
    };
    if (!res.ok || sent.success === false || !sent.result?.message_id) {
      const detail = (sent.errors ?? []).map((e) => `${e.code ?? ""} ${e.message ?? ""}`.trim()).join("; ");
      log("send_failed", { status: res.status, detail: detail.slice(0, 300) });
      return json({ ok: false, error: UNSAVED }, 502);
    }
    log("sent", {
      id: sent.result.message_id,
      company: Boolean(parsed.entry.company),
      note: Boolean(parsed.entry.note),
    });
    return json({ ok: true });
  } catch (err) {
    log("send_error", { error: err instanceof Error ? err.name : "unknown" });
    return json({ ok: false, error: UNSAVED }, 502);
  }
}

const worker = {
  async fetch(request: Request, env: Env): Promise<Response> {
    const { pathname } = new URL(request.url);
    if (pathname === "/api/waitlist") return handleWaitlist(request, env);
    if (pathname.startsWith("/api/")) return json({ ok: false, error: "Not found." }, 404);
    return env.ASSETS.fetch(request);
  },
};

export default worker;
