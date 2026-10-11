// @vitest-environment node
/**
 * checkmydata.ai is a static export on Cloudflare (SITE_EXPORT=1); the self-hosted
 * product is a standalone Next.js server. The two builds carry their headers and
 * redirects in different files, and nothing but this test compares them.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { dashboardIdFrom } from "@/app/dashboard/[id]/DashboardView";

const root = join(__dirname, "..", "..");
const read = (p: string) => readFileSync(join(root, p), "utf8");

const RETIRED = [
  "/app",
  "/app/*",
  "/login",
  "/forgot-password",
  "/reset-password",
  "/verify-email",
  "/dashboard/*",
  "/pricing",
];

describe("the hosted site's static config", () => {
  it("redirects every retired product route to the waitlist, temporarily", () => {
    const rules = read("public/_redirects")
      .split("\n")
      .filter((l) => l.trim() && !l.startsWith("#"))
      .map((l) => l.trim().split(/\s+/));
    expect(rules.map((r) => r[0]).sort()).toEqual([...RETIRED].sort());
    for (const [, to, status] of rules) {
      expect(to).toBe("/#waitlist");
      expect(status).toBe("307");
    }
  });

  it("sends every security header the standalone server sends", () => {
    const headers = read("public/_headers");
    const config = read("next.config.ts");
    const keys = [...config.matchAll(/key: "([A-Za-z-]+)"/g)].map((m) => m[1]);
    expect(keys.length).toBeGreaterThan(4);
    for (const key of keys) expect(headers).toContain(`${key}:`);
    expect(headers).toContain("frame-ancestors 'none'");
    expect(headers).toContain("object-src 'none'");
  });

  it("runs the Worker for /api/* only and serves the export", () => {
    const config = read("wrangler.jsonc");
    expect(config).toMatch(/"directory":\s*"\.\/out"/);
    expect(config).toMatch(/"run_worker_first":\s*\[\s*"\/api\/\*"\s*\]/);
    expect(config).toMatch(/"name":\s*"WAITLIST_LIMITER"/);
  });

  it("keeps the self-hosted build free of the hosted site's redirects", () => {
    const config = read("next.config.ts");
    expect(config).not.toMatch(/async\s+redirects\s*\(/);
    expect(config).toContain('process.env.SITE_EXPORT === "1"');
  });
});

describe("dashboardIdFrom", () => {
  it("uses the path segment when it is a real id", () => {
    expect(dashboardIdFrom("d1", null)).toBe("d1");
    expect(dashboardIdFrom("d1", "other")).toBe("d1");
  });

  it("uses the query behind the placeholder a running server rewrites to", () => {
    expect(dashboardIdFrom("_", "d1")).toBe("d1");
    expect(dashboardIdFrom("_", null)).toBe("");
    expect(dashboardIdFrom(undefined, undefined)).toBe("");
  });
});
