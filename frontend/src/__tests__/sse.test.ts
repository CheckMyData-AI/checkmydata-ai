import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect, vi, beforeEach } from "vitest";

const fetchMock = vi.fn();
globalThis.fetch = fetchMock;

import { subscribeToWorkflow, subscribeToAllEvents } from "@/lib/sse";

beforeEach(() => {
  fetchMock.mockReset();
  localStorage.clear();
});

function mockSSEResponse(chunks: string[]) {
  let idx = 0;
  const reader = {
    read: vi.fn(() => {
      if (idx < chunks.length) {
        const value = new TextEncoder().encode(chunks[idx++]);
        return Promise.resolve({ done: false, value });
      }
      return Promise.resolve({ done: true, value: undefined });
    }),
  };
  fetchMock.mockResolvedValueOnce({
    ok: true,
    body: { getReader: () => reader },
  });
  return reader;
}

describe("subscribeToWorkflow", () => {
  it("relies on session cookie, never a bearer header", async () => {
    // Legacy localStorage fallback removed (P2 cleanup).
    localStorage.setItem("auth_token", "my-jwt");
    mockSSEResponse([]);
    subscribeToWorkflow("wf-1", vi.fn());
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toContain("/workflows/events?workflow_id=wf-1");
    expect(opts.headers?.Authorization).toBeUndefined();
    expect(opts.credentials).toBe("include");
  });

  it("omits Authorization when no token", async () => {
    mockSSEResponse([]);
    subscribeToWorkflow("wf-2", vi.fn());
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, opts] = fetchMock.mock.calls[0];
    expect(opts.headers?.Authorization).toBeUndefined();
  });

  it("parses SSE events and calls onEvent", async () => {
    const onEvent = vi.fn();
    const eventData = JSON.stringify({
      workflow_id: "wf-1",
      step: "clone_or_pull",
      status: "completed",
      detail: "OK",
      elapsed_ms: 500,
      timestamp: 1710000000,
      pipeline: "index_repo",
      extra: {},
    });
    mockSSEResponse([`event: step\ndata: ${eventData}\n\n`]);
    subscribeToWorkflow("wf-1", onEvent);
    await vi.waitFor(() => expect(onEvent).toHaveBeenCalled());
    expect(onEvent.mock.calls[0][0].step).toBe("clone_or_pull");
    expect(onEvent.mock.calls[0][0].status).toBe("completed");
  });

  it("returns unsubscribe function that aborts", () => {
    mockSSEResponse([]);
    const unsub = subscribeToWorkflow("wf-1", vi.fn());
    expect(typeof unsub).toBe("function");
    unsub();
  });
});

describe("subscribeToAllEvents", () => {
  it("calls /workflows/events without workflow_id param", async () => {
    mockSSEResponse([]);
    subscribeToAllEvents(vi.fn());
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("/workflows/events");
    expect(url).not.toContain("workflow_id");
  });

  it("uses cookie auth instead of bearer header", async () => {
    localStorage.setItem("auth_token", "tok-123");
    mockSSEResponse([]);
    subscribeToAllEvents(vi.fn());
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, opts] = fetchMock.mock.calls[0];
    expect(opts.headers?.Authorization).toBeUndefined();
    expect(opts.credentials).toBe("include");
  });

  it("calls onError on non-ok response", async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 401, body: null });
    const onError = vi.fn();
    subscribeToAllEvents(vi.fn(), onError);
    await vi.waitFor(() => expect(onError).toHaveBeenCalled());
  });
});

describe("pipeline event allowlist — AUD-0819-03", () => {
  it("lists every event the handler has a case for", async () => {
    // The bug this locks out: the backend emitted `retrieval_degraded`, the
    // handler grew no case for it, and later the case existed while the
    // allowlist did not list it. Each omission is invisible from the other file,
    // and the symptom is silence — the exact failure the event was added to
    // prevent. Read from source because a `switch` cannot be enumerated at
    // runtime; the project already ratchets this way in pack-bans.test.ts.
    const { PIPELINE_EVENTS } = await import("@/lib/api/chat");
    const src = readFileSync(
      resolve(__dirname, "../components/chat/pipeline-event-handlers.ts"),
      "utf8",
    );
    const handled = [...src.matchAll(/case\s+"([a-z_]+)"\s*:/g)].map((m) => m[1]);
    expect(handled.length).toBeGreaterThan(5);
    const missing = handled.filter((e) => !PIPELINE_EVENTS.has(e));
    expect(missing).toEqual([]);
  });
});
