import { describe, it, expect, vi, beforeEach } from "vitest";

const fetchMock = vi.fn();
globalThis.fetch = fetchMock;

import { api } from "@/lib/api";

beforeEach(() => {
  fetchMock.mockReset();
  localStorage.clear();
});

function mockOk(data: unknown) {
  fetchMock.mockResolvedValueOnce({
    ok: true,
    json: () => Promise.resolve(data),
  });
}

function mockError(status: number, detail: string) {
  fetchMock.mockResolvedValueOnce({
    ok: false,
    status,
    json: () => Promise.resolve({ detail }),
  });
}

describe("api.projects", () => {
  it("list calls GET /projects", async () => {
    mockOk([{ id: "1", name: "P1" }]);
    const result = await api.projects.list();
    expect(result).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/projects"),
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });

  it("create calls POST /projects", async () => {
    mockOk({ id: "2", name: "New" });
    await api.projects.create({ name: "New" });
    const [, opts] = fetchMock.mock.calls[0];
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual({ name: "New" });
  });

  it("throws on error response", async () => {
    mockError(404, "Not found");
    await expect(api.projects.get("missing")).rejects.toThrow("Not found");
  });
});

describe("api auth headers", () => {
  it("sends Authorization header when token is stored", async () => {
    localStorage.setItem("auth_token", "test-jwt");
    mockOk([]);
    await api.projects.list();
    const [, opts] = fetchMock.mock.calls[0];
    expect(opts.headers.Authorization).toBe("Bearer test-jwt");
  });

  it("omits Authorization header when no token", async () => {
    mockOk([]);
    await api.projects.list();
    const [, opts] = fetchMock.mock.calls[0];
    expect(opts.headers.Authorization).toBeUndefined();
  });
});
