import { describe, expect, it } from "vitest";

import { scrubEvent, scrubText } from "@/lib/sentry-scrub";

describe("scrubText", () => {
  it("redacts bearer tokens", () => {
    const out = scrubText("Authorization: Bearer abcdef1234567890");
    expect(out).not.toContain("abcdef1234567890");
    expect(out).toContain("[redacted]");
  });

  it("redacts key=value secrets", () => {
    expect(scrubText("api_key=sk-live-12345 failed")).not.toContain(
      "sk-live-12345",
    );
    expect(scrubText("password: hunter2hunter2")).not.toContain(
      "hunter2hunter2",
    );
  });

  it("redacts credentials in URLs but keeps the username", () => {
    const out = scrubText("postgres://admin:s3cr3t@db:5432/app");
    expect(out).not.toContain("s3cr3t");
    expect(out).toContain("admin");
  });

  it("leaves plain text untouched", () => {
    expect(scrubText("division by zero")).toBe("division by zero");
  });
});

describe("scrubEvent", () => {
  it("drops request payloads, headers and cookies", () => {
    const event = scrubEvent({
      request: {
        url: "https://app.example.com/ask",
        data: { q: "secret" },
        headers: { Authorization: "Bearer x" },
        cookies: "cmd_at=t",
        query_string: "token=abc",
        env: { REMOTE_ADDR: "1.2.3.4" },
      },
    });
    expect(event.request).toEqual({ url: "https://app.example.com/ask" });
  });

  it("reduces user to opaque id", () => {
    const event = scrubEvent({
      user: { id: "u1", email: "a@b.c", ip_address: "1.1.1.1" },
    });
    expect(event.user).toEqual({ id: "u1" });
  });

  it("scrubs exception values and breadcrumbs", () => {
    const event = scrubEvent({
      exception: { values: [{ value: "fail token=abc123def" }] },
      breadcrumbs: {
        values: [{ message: "api_key=sk-test-9", data: { body: "raw" } }],
      },
    });
    expect(event.exception.values[0].value).not.toContain("abc123def");
    expect(event.breadcrumbs.values[0].message).not.toContain("sk-test-9");
    expect(event.breadcrumbs.values[0].data).toBeUndefined();
  });

  it("passes through minimal events", () => {
    expect(scrubEvent({})).toEqual({});
  });
});
