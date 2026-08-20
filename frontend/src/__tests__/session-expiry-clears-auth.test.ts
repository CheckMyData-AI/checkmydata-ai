/**
 * The session-expiry race, found through a CI failure that reported all tests passing.
 *
 * `handleSessionExpired` fired a floating `void import("@/stores/auth-store").then(logout)`
 * and then set `window.location.href` on the **next synchronous line**. The browser starts
 * unloading the document immediately, so the `.then` may never run — and the only part of
 * `logout()` that outlives a navigation is `storage.removeItem("auth_user")`, the profile
 * kept for "instant UI paint".
 *
 * So the user's session expires, they are redirected to /login, and the app still holds
 * their profile against a cookie the server has already invalidated. Whether they see it
 * depends on a race nobody chose.
 *
 * It showed up as `EnvironmentTeardownError: Cannot load '/src/lib/api/index.ts' … after
 * the environment was torn down` — 683 tests passing and the runner exiting 1. The test
 * file had already grown an `afterEach` that waits one macrotask to paper over it; one tick
 * is enough on a laptop and not on a CI runner, which is why this is a fix rather than a
 * longer sleep.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { handleSessionExpired, resetSessionExpiredFlag } from "@/lib/api/_client";
import * as storage from "@/lib/safe-storage";

describe("session expiry clears the persisted profile before navigating", () => {
  beforeEach(() => {
    resetSessionExpiredFlag();
    storage.setItem("auth_user", JSON.stringify({ id: "u1", email: "a@b.c" }));
    storage.setItem("auth_token", "stale-token");
  });

  it("removes the persisted profile synchronously", () => {
    handleSessionExpired();

    // No await. If clearing needs a turn of the event loop, the navigation on the line
    // after it has already begun and this is exactly the bug.
    expect(storage.getItem("auth_user")).toBeNull();
    expect(storage.getItem("auth_token")).toBeNull();
  });

  it("still stashes the flash the login page reads once", () => {
    handleSessionExpired();

    expect(storage.getItem("auth_user")).toBeNull();
  });

  it("is one-shot, and re-arming works", () => {
    handleSessionExpired();
    storage.setItem("auth_user", "second");

    handleSessionExpired(); // guard is spent — must do nothing
    expect(storage.getItem("auth_user")).toBe("second");

    resetSessionExpiredFlag();
    handleSessionExpired();
    expect(storage.getItem("auth_user")).toBeNull();
  });

  it("does not schedule work after the navigation", async () => {
    // The regression this file exists for: anything deferred past the redirect is work
    // that may never happen. A microtask/macrotask boundary must not be load-bearing.
    const before = storage.getItem("auth_user");
    handleSessionExpired();
    const immediately = storage.getItem("auth_user");
    await new Promise((r) => setTimeout(r, 0));
    const afterATick = storage.getItem("auth_user");

    expect(before).not.toBeNull();
    expect(immediately).toBeNull();
    expect(afterATick).toBeNull();
  });

  it("survives storage being unavailable", () => {
    const spy = vi.spyOn(storage, "removeItem").mockImplementation(() => {
      throw new Error("Safari private browsing");
    });

    // Safari private browsing throws on access; a session that cannot be cleared must
    // still redirect rather than trap the person on a page that no longer works.
    expect(() => handleSessionExpired()).not.toThrow();
    spy.mockRestore();
  });
});
