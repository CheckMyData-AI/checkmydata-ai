/**
 * B-26 / SCN-022 — the members route is capped and reports that in headers only
 * (F-PROJ-13), so `listMembersPage` must read them. `total` is null when the header is
 * missing: unknown is not zero.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

const fetchMock = vi.fn();
globalThis.fetch = fetchMock;

import { api } from "@/lib/api";

function respond(body: unknown, headers: Record<string, string>) {
  fetchMock.mockResolvedValueOnce({
    ok: true,
    status: 200,
    headers: new Headers(headers),
    json: () => Promise.resolve(body),
  });
}

beforeEach(() => fetchMock.mockReset());

describe("api.invites.listMembersPage", () => {
  it("reads the real total and the capped marker", async () => {
    respond([{ id: "m1" }], { "X-Total-Count": "500", "X-Result-Capped": "true" });
    const page = await api.invites.listMembersPage("p1");
    expect(page).toEqual({ members: [{ id: "m1" }], total: 500, capped: true });
    expect(fetchMock.mock.calls[0][0]).toContain("/invites/p1/members");
  });

  it("an uncapped list is not capped", async () => {
    respond([{ id: "m1" }], { "X-Total-Count": "1", "X-Result-Capped": "false" });
    expect(await api.invites.listMembersPage("p1")).toMatchObject({ total: 1, capped: false });
  });

  it("a missing header is unknown, not zero, and never claims capped", async () => {
    respond([{ id: "m1" }], {});
    expect(await api.invites.listMembersPage("p1")).toMatchObject({ total: null, capped: false });
  });
});
