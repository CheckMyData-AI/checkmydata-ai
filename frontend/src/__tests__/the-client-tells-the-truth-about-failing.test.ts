/**
 * Five ways the frontend mishandled a failure it had already detected.
 *
 * P1 row 13, the interface half; FE-01, FE-02, FE-03, FE-05, FE-08.
 *
 * **FE-01 / FE-08 — one root cause, two consequences.** `controller.abort(reason)`
 * with a *string* reason rejects the pending promise **with that string**, not with a
 * `DOMException`. Both catch blocks test for an object (`instanceof DOMException`, or
 * `err.name === "AbortError"`), so neither matches, and the code written for the
 * timeout has never run. In `_client.ts` that means a timed-out GET is *retried
 * twice* — one call becomes three requests and ~182 s of waiting, tripling load on a
 * backend that was already too slow to answer. In `chat.ts` it means a stalled stream
 * is reported as "An unexpected error occurred" instead of "The response timed out",
 * which is the one message that would tell the user retrying is reasonable.
 *
 * **FE-02 — a poll that lands after a navigation drags the user back.** `poll()`
 * closes over `sessionId`; the effect cleanup clears the interval but cannot cancel an
 * in-flight `Promise.all`, and nothing re-checks which session is active when it
 * resolves. `setActiveSession` also swaps the message list, so the whole panel changes
 * under the user and their click appears to have been ignored. `ChatPanel` guards the
 * same kind of write; this call site does not.
 *
 * **FE-03 — any refresh failure signs the user out.** A bare `catch` treats a 502, a
 * DNS blip and a genuine 401 identically: it deletes the persisted session and
 * `AuthGate` redirects to `/login` with no message. `refresh` is a POST, so the
 * client's retry path does not apply, and `/auth/*` is excluded from the
 * session-expiry flash. The error already carries `status`, and `logout()` in the same
 * file already discriminates on it.
 *
 * **FE-05 — a clarification question survives a reload; the way to answer it does
 * not.** `mapDtoToMessages` is the one function that rebuilds history for a reload, a
 * session switch and the background poll, and it reads eight fields out of
 * `metadata_json` — not `clarification_data`, and not `continuation_context`. The
 * amber "Question" chip comes back and the answer card does not.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

describe("FE-01 — a timed-out request is not retried", () => {
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

  it("makes exactly one request when the client's own timeout fires", async () => {
    const { request } = await import("@/lib/api/_client");

    let calls = 0;
    vi.stubGlobal("fetch", (_url: string, init: RequestInit) => {
      calls += 1;
      return new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(init.signal?.reason));
      });
    });

    await expect(request("/projects", { timeoutMs: 20 })).rejects.toThrow();

    expect(calls).toBe(1);
  });

  it("reports it as a timeout the user can act on", async () => {
    const { request } = await import("@/lib/api/_client");

    vi.stubGlobal("fetch", (_url: string, init: RequestInit) => {
      return new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(init.signal?.reason));
      });
    });

    await expect(request("/projects", { timeoutMs: 20 })).rejects.toThrow(
      /timed out\. Please try again/i,
    );
  });
});

describe("FE-08 — a stalled stream says it timed out", () => {
  it("classifies an idle-timeout abort as a timeout, not a network error", async () => {
    const { classifyStreamError } = await import("@/lib/api/chat");

    const ctrl = new AbortController();
    ctrl.abort("Stream idle timeout");

    const classified = classifyStreamError(ctrl.signal.reason, ctrl.signal, true);

    expect(classified).not.toBeNull();
    expect(classified!.error_type).toBe("timeout");
    expect(classified!.user_message).toMatch(/timed out/i);
  });

  it("stays silent for a deliberate abort", () => {
    // Stop, or a session switch: abort() with no reason. Reporting an error there
    // would put a red banner on an action the user took on purpose.
    return import("@/lib/api/chat").then(({ classifyStreamError }) => {
      const ctrl = new AbortController();
      ctrl.abort();
      expect(classifyStreamError(ctrl.signal.reason, ctrl.signal, false)).toBeNull();
    });
  });
});

describe("FE-02 — a poll that lands after a navigation is discarded", () => {
  it("does not switch the panel back to the session the user just left", async () => {
    const { useAppStore } = await import("@/stores/app-store");
    const { applyPolledSession } = await import("@/hooks/useSessionPolling");

    const store = useAppStore.getState();
    store.setActiveSession({ id: "B", title: "B", status: "idle" } as never);

    const applied = applyPolledSession(
      "A",
      { id: "A", title: "A", status: "processing" } as never,
    );

    expect(applied).toBe(false);
    expect(useAppStore.getState().activeSession?.id).toBe("B");
  });

  it("still applies the poll when the user never left", async () => {
    const { useAppStore } = await import("@/stores/app-store");
    const { applyPolledSession } = await import("@/hooks/useSessionPolling");

    const store = useAppStore.getState();
    store.setActiveSession({ id: "A", title: "A", status: "processing" } as never);

    const applied = applyPolledSession(
      "A",
      { id: "A", title: "A renamed", status: "idle" } as never,
    );

    expect(applied).toBe(true);
    expect(useAppStore.getState().activeSession?.title).toBe("A renamed");
  });
});

describe("FE-03 — only a 401 signs the user out", () => {
  beforeEach(() => {
    const mem: Record<string, string> = {};
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => mem[k] ?? null,
      setItem: (k: string, v: string) => {
        mem[k] = v;
      },
      removeItem: (k: string) => {
        delete mem[k];
      },
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("keeps the session when the refresh fails with a 502", async () => {
    const { useAuthStore } = await import("@/stores/auth-store");
    const { api } = await import("@/lib/api");

    localStorage.setItem("auth_user", JSON.stringify({ id: "u1", email: "a@b.c" }));
    const err = Object.assign(new Error("Bad Gateway"), { status: 502 });
    vi.spyOn(api.auth, "refresh").mockRejectedValue(err);

    await useAuthStore.getState().restore();

    expect(localStorage.getItem("auth_user")).not.toBeNull();
    expect(useAuthStore.getState().user).not.toBeNull();
  });

  it("signs the user out when the refresh fails with a 401", async () => {
    const { useAuthStore } = await import("@/stores/auth-store");
    const { api } = await import("@/lib/api");

    localStorage.setItem("auth_user", JSON.stringify({ id: "u1", email: "a@b.c" }));
    const err = Object.assign(new Error("Unauthorized"), { status: 401 });
    vi.spyOn(api.auth, "refresh").mockRejectedValue(err);

    await useAuthStore.getState().restore();

    expect(localStorage.getItem("auth_user")).toBeNull();
    expect(useAuthStore.getState().user).toBeNull();
  });
});

describe("FE-05 — a reloaded clarification can still be answered", () => {
  it("restores the payload the answer card needs", async () => {
    const { mapDtoToMessages } = await import("@/components/chat/ChatSessionList");

    const [msg] = mapDtoToMessages([
      {
        id: "m1",
        role: "assistant",
        content: "Which date range did you mean?",
        metadata_json: JSON.stringify({
          response_type: "clarification_request",
          clarification_data: {
            question: "Which date range did you mean?",
            question_type: "multiple_choice",
            options: ["Last 7 days", "Last 30 days", "This year"],
          },
        }),
        created_at: new Date().toISOString(),
      },
    ]);

    expect(msg.responseType).toBe("clarification_request");
    expect(msg.clarificationData?.options).toHaveLength(3);
  });

  it("restores the continuation context the Continue button passes back", async () => {
    const { mapDtoToMessages } = await import("@/components/chat/ChatSessionList");

    const [msg] = mapDtoToMessages([
      {
        id: "m2",
        role: "assistant",
        content: "I ran out of steps.",
        metadata_json: JSON.stringify({
          response_type: "step_limit_reached",
          continuation_context: "stage-3-partial-results",
        }),
        created_at: new Date().toISOString(),
      },
    ]);

    expect(msg.responseType).toBe("step_limit_reached");
    expect(msg.continuationContext).toBe("stage-3-partial-results");
  });
});
