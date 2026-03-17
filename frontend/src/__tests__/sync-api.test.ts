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

describe("api.connections.sync", () => {
  it("triggerSync calls POST /connections/{id}/sync", async () => {
    mockOk({ status: "started", connection_id: "c1" });
    const result = await api.connections.triggerSync("c1");
    expect(result.status).toBe("started");
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toContain("/connections/c1/sync");
    expect(opts.method).toBe("POST");
  });

  it("syncStatus calls GET /connections/{id}/sync/status", async () => {
    mockOk({ is_synced: true, is_syncing: false, synced_tables: 5, total_tables: 10 });
    const result = await api.connections.syncStatus("c1");
    expect(result.is_synced).toBe(true);
    expect(result.synced_tables).toBe(5);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("/connections/c1/sync/status");
  });

  it("getSync calls GET /connections/{id}/sync", async () => {
    mockOk({ tables: [{ table_name: "orders", sync_status: "matched" }], summary: null });
    const result = await api.connections.getSync("c1");
    expect(result.tables).toHaveLength(1);
    expect(result.tables[0].table_name).toBe("orders");
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("/connections/c1/sync");
    expect(url).not.toContain("status");
  });

  it("deleteSync calls DELETE /connections/{id}/sync", async () => {
    mockOk({ ok: true });
    const result = await api.connections.deleteSync("c1");
    expect(result.ok).toBe(true);
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toContain("/connections/c1/sync");
    expect(opts.method).toBe("DELETE");
  });
});

describe("api.projects.readiness", () => {
  it("calls GET /projects/{id}/readiness", async () => {
    mockOk({
      repo_connected: true,
      repo_indexed: true,
      db_connected: true,
      db_indexed: true,
      code_db_synced: false,
      ready: false,
      missing_steps: [{ step: "sync", label: "Run Code-DB Sync" }],
      active_connection_id: "c1",
    });
    const result = await api.projects.readiness("p1");
    expect(result.ready).toBe(false);
    expect(result.missing_steps).toHaveLength(1);
    expect(result.missing_steps[0].step).toBe("sync");
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("/projects/p1/readiness");
  });
});
