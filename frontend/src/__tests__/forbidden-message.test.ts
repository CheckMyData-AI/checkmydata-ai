/**
 * B-27 D4 (SCN-015, SCN-069): a 403 carries the reason, written for a person. The
 * client used to replace every one with the same generic sentence.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

const fetchMock = vi.fn();
globalThis.fetch = fetchMock;

import { api } from "@/lib/api";
import { forbiddenMessage } from "@/lib/api/_client";

beforeEach(() => fetchMock.mockReset());

describe("forbiddenMessage", () => {
  it("shows the backend's reason", () => {
    expect(forbiddenMessage("Requires at least 'editor' role")).toBe(
      "Requires at least 'editor' role",
    );
  });

  it("falls back when there is no usable reason", () => {
    for (const d of [undefined, null, "", "   ", { msg: "x" }]) {
      expect(forbiddenMessage(d)).toBe("You don't have permission to perform this action.");
    }
  });

  it("turns a CSRF refusal into what fixes it", () => {
    expect(forbiddenMessage("CSRF token missing or invalid")).toMatch(/Reload the page/);
  });
});

describe("request() on a 403", () => {
  it("rejects with the reason the server gave, and the status", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: () => Promise.resolve({ detail: "This invite is for a different email address" }),
    });
    await expect(api.invites.decline("inv1")).rejects.toMatchObject({
      message: "This invite is for a different email address",
      status: 403,
    });
  });
});
