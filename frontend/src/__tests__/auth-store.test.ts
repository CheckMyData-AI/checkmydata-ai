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

  it("register stores user and token", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        token: "jwt-reg",
        user: { id: "u2", email: "new@b.com", display_name: "New" },
      }),
    });

    await useAuthStore.getState().register("new@b.com", "password1", "New");
    const state = useAuthStore.getState();
    expect(state.user?.email).toBe("new@b.com");
    expect(state.token).toBe("jwt-reg");
  });

  it("register sets error on failure", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: () => Promise.resolve({ detail: "Email already registered" }),
    });

    await useAuthStore.getState().register("dup@b.com", "password1");
    expect(useAuthStore.getState().error).toBe("Email already registered");
  });

  it("googleLogin stores user and token", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        token: "jwt-google",
        user: { id: "u3", email: "g@b.com", display_name: "G" },
      }),
    });

    await useAuthStore.getState().googleLogin("cred", "nonce1", "csrf1");
    const state = useAuthStore.getState();
    expect(state.user?.email).toBe("g@b.com");
    expect(state.token).toBe("jwt-google");
  });

  it("googleLogin sends nonce and csrf token", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        token: "jwt-g2",
        user: { id: "u4", email: "g2@b.com", display_name: "G2" },
      }),
    });

    await useAuthStore.getState().googleLogin("cred-val", "my-nonce", "my-csrf");
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.credential).toBe("cred-val");
    expect(body.nonce).toBe("my-nonce");
    expect(body.g_csrf_token).toBe("my-csrf");
  });

  it("logout clears state and localStorage", async () => {
    localStorage.setItem("auth_token", "jwt");
    localStorage.setItem("auth_user", '{"id":"u1"}');
    useAuthStore.setState({ user: { id: "u1", email: "a@b.com", display_name: "A" }, token: "jwt" });

    useAuthStore.getState().logout();
    expect(useAuthStore.getState().user).toBeNull();
    expect(localStorage.getItem("auth_token")).toBeNull();
  });

  it("restore reads from localStorage and validates via /me", async () => {
    const user = { id: "u1", email: "saved@b.com", display_name: "S" };
    localStorage.setItem("auth_token", "jwt-saved");
    localStorage.setItem("auth_user", JSON.stringify(user));

    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(user),
    });

    useAuthStore.getState().restore();
    expect(useAuthStore.getState().user?.email).toBe("saved@b.com");
    expect(useAuthStore.getState().token).toBe("jwt-saved");
  });

  it("restore clears state when /me fails", async () => {
    localStorage.setItem("auth_token", "jwt-expired");
    localStorage.setItem("auth_user", JSON.stringify({ id: "u1", email: "x@b.com", display_name: "X" }));

    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: "Invalid or expired token" }),
    });

    useAuthStore.getState().restore();
    expect(useAuthStore.getState().token).toBe("jwt-expired");

    await vi.waitFor(() => {
      expect(useAuthStore.getState().user).toBeNull();
    });
    expect(localStorage.getItem("auth_token")).toBeNull();
  });
});
