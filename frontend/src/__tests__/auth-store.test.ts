import { describe, it, expect, vi, beforeEach } from "vitest";
import { useAuthStore } from "@/stores/auth-store";

const fetchMock = vi.fn();
globalThis.fetch = fetchMock;

beforeEach(() => {
  fetchMock.mockReset();
  localStorage.clear();
  useAuthStore.setState({ user: null, token: null, isLoading: false, error: null });
});

describe("auth store", () => {
  it("login stores user and token", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        token: "jwt-123",
        user: { id: "u1", email: "a@b.com", display_name: "A" },
      }),
    });

    await useAuthStore.getState().login("a@b.com", "pass");
    const state = useAuthStore.getState();
    expect(state.user?.email).toBe("a@b.com");
    expect(state.token).toBe("jwt-123");
    expect(localStorage.getItem("auth_token")).toBe("jwt-123");
  });

  it("login sets error on failure", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: "Invalid credentials" }),
    });

    await useAuthStore.getState().login("a@b.com", "wrong");
    expect(useAuthStore.getState().error).toBe("Invalid credentials");
  });

  it("logout clears state and localStorage", async () => {
    localStorage.setItem("auth_token", "jwt");
    localStorage.setItem("auth_user", '{"id":"u1"}');
    useAuthStore.setState({ user: { id: "u1", email: "a@b.com", display_name: "A" }, token: "jwt" });

    useAuthStore.getState().logout();
    expect(useAuthStore.getState().user).toBeNull();
    expect(localStorage.getItem("auth_token")).toBeNull();
  });

  it("restore reads from localStorage", () => {
    localStorage.setItem("auth_token", "jwt-saved");
    localStorage.setItem("auth_user", JSON.stringify({ id: "u1", email: "saved@b.com", display_name: "S" }));

    useAuthStore.getState().restore();
    expect(useAuthStore.getState().user?.email).toBe("saved@b.com");
    expect(useAuthStore.getState().token).toBe("jwt-saved");
  });
});
