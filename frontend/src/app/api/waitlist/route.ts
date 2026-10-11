import { NextResponse } from "next/server";
import { parseWaitlist, waitlistEmail } from "@/lib/waitlist";

/**
 * POST /api/waitlist — mails one sign-up to the team inbox through Resend.
 *
 * Runs inside the site's own Next.js server: the product backend is switched off,
 * so nothing else could receive it. A sign-up that cannot be mailed is reported
 * as a failure to the visitor — it is never acknowledged and then dropped.
 */

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const RESEND_URL = "https://api.resend.com/emails";
const DEFAULT_TO = "contact@checkmydata.ai";
const DEFAULT_FROM = "CheckMyData <noreply@checkmydata.ai>";

// One web dyno, so an in-process window is the whole picture.
const WINDOW_MS = 10 * 60 * 1000;
const MAX_PER_WINDOW = 5;
const hits = new Map<string, number[]>();

function limited(key: string, now: number): boolean {
  const recent = (hits.get(key) ?? []).filter((t) => now - t < WINDOW_MS);
  if (recent.length >= MAX_PER_WINDOW) {
    hits.set(key, recent);
    return true;
  }
  recent.push(now);
  hits.set(key, recent);
  if (hits.size > 5000) {
    for (const [k, times] of hits) {
      if (!times.some((t) => now - t < WINDOW_MS)) hits.delete(k);
    }
  }
  return false;
}

/** Structured, and without the visitor's address: the inbox holds that, the log does not. */
function log(event: string, fields: Record<string, unknown> = {}) {
  console.log(JSON.stringify({ at: new Date().toISOString(), scope: "waitlist", event, ...fields }));
}

export async function POST(request: Request) {
  const ip = (request.headers.get("x-forwarded-for") ?? "").split(",")[0].trim() || "unknown";
  if (limited(ip, Date.now())) {
    log("rate_limited");
    return NextResponse.json(
      { ok: false, error: "Too many sign-ups from here. Try again in a few minutes." },
      { status: 429 },
    );
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Send the form as JSON." }, { status: 400 });
  }

  const parsed = parseWaitlist(body);
  if (!parsed.ok) {
    if (parsed.reason === "bot") {
      log("honeypot");
      return NextResponse.json({ ok: true });
    }
    return NextResponse.json(
      { ok: false, field: parsed.field, error: parsed.message },
      { status: 422 },
    );
  }

  const apiKey = process.env.RESEND_API_KEY;
  if (!apiKey) {
    log("not_configured", { missing: "RESEND_API_KEY" });
    return NextResponse.json(
      { ok: false, error: "Sign-ups are briefly unavailable. Email contact@checkmydata.ai instead." },
      { status: 503 },
    );
  }

  const { subject, text } = waitlistEmail(parsed.entry);
  try {
    const res = await fetch(RESEND_URL, {
      method: "POST",
      headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        from: process.env.WAITLIST_FROM || DEFAULT_FROM,
        to: [process.env.WAITLIST_TO || DEFAULT_TO],
        reply_to: parsed.entry.email,
        subject,
        text,
      }),
      signal: AbortSignal.timeout(10_000),
    });
    if (!res.ok) {
      log("send_failed", { status: res.status, detail: (await res.text()).slice(0, 300) });
      return NextResponse.json(
        { ok: false, error: "We couldn't save your sign-up. Try again, or email contact@checkmydata.ai." },
        { status: 502 },
      );
    }
    const sent = (await res.json().catch(() => ({}))) as { id?: string };
    log("sent", { id: sent.id ?? null, company: Boolean(parsed.entry.company), note: Boolean(parsed.entry.note) });
    return NextResponse.json({ ok: true });
  } catch (err) {
    log("send_error", { error: err instanceof Error ? err.name : "unknown" });
    return NextResponse.json(
      { ok: false, error: "We couldn't save your sign-up. Try again, or email contact@checkmydata.ai." },
      { status: 502 },
    );
  }
}
