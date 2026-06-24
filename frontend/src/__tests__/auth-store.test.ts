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
  it("login stores user in memory but never persists the token (T-SEC-3)", async () => {
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
    // The JWT now rides in an httpOnly cookie — it must NOT touch storage.
    expect(localStorage.getItem("auth_token")).toBeNull();
    // Only the non-sensitive profile is cached for instant UI paint.
    expect(localStorage.getItem("auth_user")).toContain("a@b.com");
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

  it("logout clears state and storage and calls the logout endpoint", async () => {
    // logout() fires a best-effort POST /auth/logout to clear server cookies.
    fetchMock.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ok: true }) });
    localStorage.setItem("auth_token", "jwt");
    localStorage.setItem("auth_user", '{"id":"u1"}');
    useAuthStore.setState({ user: { id: "u1", email: "a@b.com", display_name: "A" }, token: "jwt" });

    useAuthStore.getState().logout();
    expect(useAuthStore.getState().user).toBeNull();
    expect(localStorage.getItem("auth_token")).toBeNull();
    expect(localStorage.getItem("auth_user")).toBeNull();
  });

  it("restore validates the cookie session via refresh", async () => {
    const user = { id: "u1", email: "saved@b.com", display_name: "S" };
    localStorage.setItem("auth_user", JSON.stringify(user));

    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ token: "jwt-fresh", user }),
    });

    await useAuthStore.getState().restore();
    expect(useAuthStore.getState().user?.email).toBe("saved@b.com");
    expect(useAuthStore.getState().token).toBe("jwt-fresh");
  });

  it("schedules proactive refresh from expires_in when the token body is empty (cookie auth)", async () => {
    // F-AUTH-04: under cookie auth the response token is "" — refresh scheduling
    // must use expires_in instead of decoding the (absent) JWT.
    vi.useFakeTimers();
    try {
      fetchMock.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            token: "",
            expires_in: 3600, // 60 min; refresh fires 30 min before expiry
            user: { id: "u1", email: "c@b.com", display_name: "C" },
          }),
      });
      await useAuthStore.getState().login("c@b.com", "pass");
      expect(useAuthStore.getState().user?.email).toBe("c@b.com");
      expect(fetchMock).toHaveBeenCalledTimes(1);

      fetchMock.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            token: "",
            expires_in: 3600,
            user: { id: "u1", email: "c@b.com", display_name: "C" },
          }),
      });
      await vi.advanceTimersByTimeAsync(31 * 60 * 1000);
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(String(fetchMock.mock.calls[1][0])).toContain("/auth/refresh");
    } finally {
      useAuthStore.getState().logout();
      vi.useRealTimers();
    }
  });

  it("restore clears state when refresh fails", async () => {
    localStorage.setItem("auth_user", JSON.stringify({ id: "u1", email: "x@b.com", display_name: "X" }));

    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: "Invalid or expired token" }),
    });

    await useAuthStore.getState().restore();
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().token).toBeNull();
    expect(localStorage.getItem("auth_user")).toBeNull();
  });
});
