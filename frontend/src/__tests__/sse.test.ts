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
  it("sends Authorization header when token exists", async () => {
    localStorage.setItem("auth_token", "my-jwt");
    mockSSEResponse([]);
    subscribeToWorkflow("wf-1", vi.fn());
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toContain("/workflows/events?workflow_id=wf-1");
    expect(opts.headers.Authorization).toBe("Bearer my-jwt");
  });

  it("omits Authorization when no token", async () => {
    mockSSEResponse([]);
    subscribeToWorkflow("wf-2", vi.fn());
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, opts] = fetchMock.mock.calls[0];
    expect(opts.headers.Authorization).toBeUndefined();
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

  it("sends auth header", async () => {
    localStorage.setItem("auth_token", "tok-123");
    mockSSEResponse([]);
    subscribeToAllEvents(vi.fn());
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, opts] = fetchMock.mock.calls[0];
    expect(opts.headers.Authorization).toBe("Bearer tok-123");
  });

  it("calls onError on non-ok response", async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 401, body: null });
    const onError = vi.fn();
    subscribeToAllEvents(vi.fn(), onError);
    await vi.waitFor(() => expect(onError).toHaveBeenCalled());
  });
});
