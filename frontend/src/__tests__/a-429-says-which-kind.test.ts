/**
 * A 429 that resets tomorrow was shown as one that resets in a moment.
 *
 * P2 row 17, the interface half of API-06. The backend serves two different
 * conditions as `429`: the rate limiter ("wait a moment") and token-budget
 * exhaustion ("upgrade, or come back next month"). The client discarded the body
 * for that status entirely and threw a fixed string, so the message the backend
 * composed — the one naming `/pricing` — never reached anybody, and a user whose
 * monthly budget was spent was told to wait a moment.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

function _jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("API-06 — the 429 body reaches the user", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("surfaces a budget-exhaustion message instead of 'wait a moment'", async () => {
    const { request } = await import("@/lib/api/_client");

    vi.stubGlobal("fetch", async () =>
      // The shape FastAPI produces for `HTTPException(429, detail={...})`.
      _jsonResponse(429, {
        detail: {
          message: "Monthly token budget spent. Upgrade your plan at /pricing.",
          error_type: "token_budget",
          is_retryable: false,
        },
      }),
    );

    await expect(request("/chat/ask", { method: "POST" })).rejects.toThrow(/pricing/i);
  });

  it("still says wait a moment for the rate limiter", async () => {
    const { request } = await import("@/lib/api/_client");

    vi.stubGlobal("fetch", async () =>
      _jsonResponse(429, {
        detail: "Rate limit exceeded: 20 per 1 minute",
        error_type: "rate_limit",
        is_retryable: true,
      }),
    );

    await expect(request("/chat/ask", { method: "POST" })).rejects.toThrow(/moment/i);
  });

  it("falls back to the old wording when the body says nothing", async () => {
    const { request } = await import("@/lib/api/_client");

    vi.stubGlobal("fetch", async () => new Response("", { status: 429 }));

    await expect(request("/chat/ask", { method: "POST" })).rejects.toThrow(/Too many requests/i);
  });
});
