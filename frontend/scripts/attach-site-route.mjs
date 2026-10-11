#!/usr/bin/env node
/**
 * Puts the site Worker in front of checkmydata.ai — idempotently.
 *
 * `wrangler deploy` runs with a token that may deploy scripts on the account and
 * nothing else; a route is a ZONE right (Workers Routes Write), so it is attached
 * here with its own zone-scoped token, CLOUDFLARE_ROUTES_TOKEN. The apex DNS record
 * is proxied, so once the route exists Cloudflare answers from the Worker and the
 * origin behind the record is never reached — no DNS change, no downtime.
 *
 * Usage: CLOUDFLARE_ROUTES_TOKEN=… node scripts/attach-site-route.mjs
 * Exit 0 when the route points at the Worker (created, moved or already there).
 */

const ZONE = "checkmydata.ai";
const PATTERN = "checkmydata.ai/*";
const SCRIPT = "checkmydata-site";
const API = "https://api.cloudflare.com/client/v4";

const token = process.env.CLOUDFLARE_ROUTES_TOKEN;
if (!token) {
  console.error("CLOUDFLARE_ROUTES_TOKEN is not set");
  process.exit(2);
}

async function call(path, init = {}) {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok || body.success === false) {
    const errors = (body.errors ?? []).map((e) => `${e.code} ${e.message}`).join("; ");
    throw new Error(`${init.method ?? "GET"} ${path} → HTTP ${res.status} ${errors}`);
  }
  return body.result;
}

const zones = await call(`/zones?name=${ZONE}`);
if (!zones.length) throw new Error(`zone ${ZONE} is not visible to this token`);
const zoneId = zones[0].id;

const routes = await call(`/zones/${zoneId}/workers/routes`);
const existing = routes.find((r) => r.pattern === PATTERN);

if (existing && existing.script === SCRIPT) {
  console.log(`route ${PATTERN} → ${SCRIPT}: already in place`);
} else if (existing) {
  await call(`/zones/${zoneId}/workers/routes/${existing.id}`, {
    method: "PUT",
    body: JSON.stringify({ pattern: PATTERN, script: SCRIPT }),
  });
  console.log(`route ${PATTERN}: moved from ${existing.script || "(none)"} to ${SCRIPT}`);
} else {
  await call(`/zones/${zoneId}/workers/routes`, {
    method: "POST",
    body: JSON.stringify({ pattern: PATTERN, script: SCRIPT }),
  });
  console.log(`route ${PATTERN} → ${SCRIPT}: created`);
}
