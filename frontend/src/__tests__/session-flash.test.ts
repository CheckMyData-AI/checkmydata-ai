import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.fn();
globalThis.fetch = fetchMock;

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

import {
  request,
  handleSessionExpired,
  resetSessionExpiredFlag,
} from "@/lib/api/_client";
import {
  SESSION_EXPIRED_MESSAGE,
  consumeSessionFlash,
  setSessionFlash,
} from "@/lib/session-flash";
import { toast } from "@/stores/toast-store";

beforeEach(() => {
  fetchMock.mockReset();
  vi.mocked(toast).mockClear();
  sessionStorage.clear();
  resetSessionExpiredFlag();
});

/**
 * The `afterEach` that used to sit here waited one macrotask for a floating
 * `void import(…)` in `handleSessionExpired` to land. That import is gone — the session
 * teardown is synchronous now, because anything deferred past `window.location.href` may
 * never run at all (see `session-expiry-clears-auth.test.ts`).
 *
 * The wait is removed deliberately rather than left as harmless: it was the visible half
 * of a real bug, and keeping it would hide the regression if the floating import ever
 * came back. One tick was enough on a laptop and not on a CI runner, which is how this
 * surfaced — `EnvironmentTeardownError` with all 683 tests passing and the runner
 * exiting 1.
 */

describe("session flash (FA-010)", () => {
  it("consumeSessionFlash returns the stashed message once, then null", () => {
    setSessionFlash(SESSION_EXPIRED_MESSAGE);
    expect(consumeSessionFlash()).toBe(SESSION_EXPIRED_MESSAGE);
    expect(consumeSessionFlash()).toBeNull();
  });

  it("401 on a non-auth route stashes the flash before the hard redirect", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: () => Promise.resolve({}),
    });

    await expect(request("/projects")).rejects.toThrow(SESSION_EXPIRED_MESSAGE);
    expect(consumeSessionFlash()).toBe(SESSION_EXPIRED_MESSAGE);
    // Toast and thrown error use the same unified text (M2).
    expect(toast).toHaveBeenCalledWith(SESSION_EXPIRED_MESSAGE, "error");
  });

  it("401 on an auth route does not stash a flash", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: "Invalid credentials" }),
    });

    await expect(
      request("/auth/login", { method: "POST" }),
    ).rejects.toThrow("Invalid credentials");
    expect(consumeSessionFlash()).toBeNull();
  });

  it("handleSessionExpired is one-shot until resetSessionExpiredFlag re-arms it (M1)", () => {
    handleSessionExpired();
    handleSessionExpired(); // blocked by the one-shot guard
    expect(consumeSessionFlash()).toBe(SESSION_EXPIRED_MESSAGE);
    expect(consumeSessionFlash()).toBeNull();

    resetSessionExpiredFlag();
    handleSessionExpired();
    expect(consumeSessionFlash()).toBe(SESSION_EXPIRED_MESSAGE);
  });
});
