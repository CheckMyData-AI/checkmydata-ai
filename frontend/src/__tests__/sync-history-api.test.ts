import { describe, it, expect, vi, beforeEach } from "vitest";
import { api } from "@/lib/api";

vi.mock("@/lib/api/_client", () => ({
  request: vi.fn(async (path: string) => ({ __path: path, runs: [] })),
}));

describe("api.projects.syncHistory", () => {
  beforeEach(() => vi.clearAllMocks());
  it("calls the sync-history endpoint with a limit", async () => {
    const res = (await api.projects.syncHistory("p1", 10)) as unknown as { __path: string };
    expect(res.__path).toBe("/projects/p1/sync-history?limit=10");
  });
  it("defaults limit to 20", async () => {
    const res = (await api.projects.syncHistory("p1")) as unknown as { __path: string };
    expect(res.__path).toBe("/projects/p1/sync-history?limit=20");
  });
});
