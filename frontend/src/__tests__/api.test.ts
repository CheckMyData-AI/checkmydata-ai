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

  it("create sends all 6 LLM fields", async () => {
    const llmData = {
      name: "LLM Project",
      indexing_llm_provider: "openai",
      indexing_llm_model: "gpt-4o",
      agent_llm_provider: "anthropic",
      agent_llm_model: "claude-3-opus",
      sql_llm_provider: "openrouter",
      sql_llm_model: "mixtral-8x7b",
    };
    mockOk({ id: "3", ...llmData });
    await api.projects.create(llmData);
    const [, opts] = fetchMock.mock.calls[0];
    const body = JSON.parse(opts.body);
    expect(body.indexing_llm_provider).toBe("openai");
    expect(body.indexing_llm_model).toBe("gpt-4o");
    expect(body.agent_llm_provider).toBe("anthropic");
    expect(body.agent_llm_model).toBe("claude-3-opus");
    expect(body.sql_llm_provider).toBe("openrouter");
    expect(body.sql_llm_model).toBe("mixtral-8x7b");
  });

  it("update sends partial LLM fields", async () => {
    mockOk({ id: "4", name: "P", agent_llm_provider: "openai" });
    await api.projects.update("4", { agent_llm_provider: "openai" });
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toContain("/projects/4");
    expect(opts.method).toBe("PATCH");
    const body = JSON.parse(opts.body);
    expect(body.agent_llm_provider).toBe("openai");
    expect(body.indexing_llm_provider).toBeUndefined();
  });

  it("create with null LLM fields", async () => {
    const data = {
      name: "No LLM",
      indexing_llm_provider: null,
      agent_llm_provider: null,
      sql_llm_provider: null,
    };
    mockOk({ id: "5", ...data });
    await api.projects.create(data);
    const [, opts] = fetchMock.mock.calls[0];
    const body = JSON.parse(opts.body);
    expect(body.indexing_llm_provider).toBeNull();
    expect(body.agent_llm_provider).toBeNull();
    expect(body.sql_llm_provider).toBeNull();
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
