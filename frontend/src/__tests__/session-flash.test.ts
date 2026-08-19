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
 * `handleSessionExpired` fires a deliberately floating `void import(…)` — the
 * lazy import that keeps `auth-store` out of a module cycle. In a browser the
 * document is unloading a line later and nobody waits for it; under vitest the
 * test finishes first, the environment tears down, and the import lands in a
 * dead realm as an `EnvironmentTeardownError`. Every test still PASSED and the
 * runner still exited 1, which is exactly the kind of red nobody reads.
 *
 * One turn of the event loop is all it needs, and it is a test-side wait rather
 * than a change to production semantics.
 */
afterEach(async () => {
  await new Promise((resolve) => setTimeout(resolve, 0));
});

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
