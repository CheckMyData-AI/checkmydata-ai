// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parseWaitlist, waitlistEmail, WAITLIST_LIMITS } from "@/lib/waitlist";

describe("parseWaitlist", () => {
  it("accepts an email alone and normalises it", () => {
    const r = parseWaitlist({ email: "  Ana@Example.COM " });
    expect(r).toEqual({ ok: true, entry: { email: "ana@example.com", name: "", company: "", note: "" } });
  });

  it("refuses a missing or malformed email, naming the field", () => {
    for (const email of [undefined, "", "ana", "ana@example", "a b@example.com"]) {
      const r = parseWaitlist({ email });
      expect(r.ok).toBe(false);
      if (!r.ok && r.reason === "invalid") expect(r.field).toBe("email");
    }
  });

  it("refuses an over-long optional field", () => {
    const r = parseWaitlist({ email: "a@b.co", note: "x".repeat(WAITLIST_LIMITS.note + 1) });
    expect(r).toMatchObject({ ok: false, reason: "invalid", field: "note" });
  });

  it("treats a filled honeypot as a bot", () => {
    expect(parseWaitlist({ email: "a@b.co", website: "spam.example" })).toEqual({ ok: false, reason: "bot" });
  });

  it("survives a body that is not an object", () => {
    expect(parseWaitlist(null)).toMatchObject({ ok: false, field: "email" });
    expect(parseWaitlist("email=a@b.co")).toMatchObject({ ok: false, field: "email" });
  });
});

describe("waitlistEmail", () => {
  it("puts who signed up in the subject and every field in the body", () => {
    const mail = waitlistEmail({ email: "a@b.co", name: "Ana", company: "Acme", note: "Churn by plan" });
    expect(mail.subject).toBe("Waitlist: Ana (Acme)");
    expect(mail.text).toContain("a@b.co");
    expect(mail.text).toContain("Churn by plan");
  });

  it("falls back to the email when no name is given", () => {
    expect(waitlistEmail({ email: "a@b.co", name: "", company: "", note: "" }).subject).toBe("Waitlist: a@b.co");
  });
});

describe("POST /api/waitlist", () => {
  const fetchMock = vi.fn();
  let ipCounter = 0;

  function req(body: unknown, ip = `10.0.0.${++ipCounter}`) {
    return new Request("http://localhost/api/waitlist", {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-forwarded-for": ip },
      body: typeof body === "string" ? body : JSON.stringify(body),
    });
  }

  async function post(body: unknown, ip?: string) {
    const { POST } = await import("@/app/api/waitlist/route");
    const res = await POST(req(body, ip));
    return { status: res.status, json: (await res.json()) as Record<string, unknown> };
  }

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(console, "log").mockImplementation(() => {});
    process.env.RESEND_API_KEY = "test-key";
    delete process.env.WAITLIST_TO;
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete process.env.RESEND_API_KEY;
  });

  it("mails the sign-up to contact@ with the visitor as reply-to", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ id: "msg_1" }), { status: 200 }));
    const { status, json } = await post({ email: "ana@example.com", name: "Ana" });
    expect(status).toBe(200);
    expect(json).toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://api.resend.com/emails");
    const sent = JSON.parse(String(init.body));
    expect(sent.to).toEqual(["contact@checkmydata.ai"]);
    expect(sent.reply_to).toBe("ana@example.com");
    expect(sent.subject).toBe("Waitlist: Ana");
  });

  it("reports a provider refusal as a failure, never as success", async () => {
    fetchMock.mockResolvedValue(new Response("domain not verified", { status: 403 }));
    const { status, json } = await post({ email: "ana@example.com" });
    expect(status).toBe(502);
    expect(json.ok).toBe(false);
  });

  it("reports a network error as a failure", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    expect((await post({ email: "ana@example.com" })).status).toBe(502);
  });

  it("answers 503 and sends nothing when the key is missing", async () => {
    delete process.env.RESEND_API_KEY;
    expect((await post({ email: "ana@example.com" })).status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns 422 with the field for invalid input, sending nothing", async () => {
    const { status, json } = await post({ email: "nope" });
    expect(status).toBe(422);
    expect(json.field).toBe("email");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns 400 for a body that is not JSON", async () => {
    expect((await post("email=a@b.co")).status).toBe(400);
  });

  it("pretends success to a bot and sends nothing", async () => {
    const { status } = await post({ email: "a@b.co", website: "x" });
    expect(status).toBe(200);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("limits one address to five sign-ups per window", async () => {
    fetchMock.mockImplementation(async () => new Response("{}", { status: 200 }));
    const statuses = [];
    for (let i = 0; i < 6; i++) statuses.push((await post({ email: `a${i}@b.co` }, "203.0.113.9")).status);
    expect(statuses).toEqual([200, 200, 200, 200, 200, 429]);
  });
});
