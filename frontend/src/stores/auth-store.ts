import { create } from "zustand";
import { api, type AuthUser } from "@/lib/api";
import * as storage from "@/lib/safe-storage";
import { toast } from "@/stores/toast-store";

const REFRESH_THRESHOLD_MS = 30 * 60 * 1000; // 30 minutes

interface AuthState {
  user: AuthUser | null;
  token: string | null;
  isLoading: boolean;
  error: string | null;

  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName?: string) => Promise<void>;
  googleLogin: (credential: string, nonce?: string, csrfToken?: string) => Promise<void>;
  logout: () => void;
  restore: () => Promise<void>;
}

function storeAuth(set: (s: Partial<AuthState>) => void, res: { token: string; user: AuthUser }) {
  storage.setItem("auth_token", res.token);
  storage.setItem("auth_user", JSON.stringify(res.user));
  set({ user: res.user, token: res.token, isLoading: false });
}

function base64UrlDecode(str: string): string {
  let s = str.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  return atob(s);
}

function getTokenExpMs(token: string): number | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const payload = JSON.parse(base64UrlDecode(parts[1]));
    return payload.exp ? payload.exp * 1000 : null;
  } catch {
    return null;
  }
}

let refreshTimer: ReturnType<typeof setTimeout> | null = null;

function scheduleRefresh(set: (s: Partial<AuthState>) => void) {
  if (refreshTimer) clearTimeout(refreshTimer);
  const token = storage.getItem("auth_token");
  if (!token) return;

  const expMs = getTokenExpMs(token);
  if (!expMs) return;

  const remaining = expMs - Date.now();
  if (remaining <= 0) {
    toast("Your session has expired. Please log in again.", "error");
    setTimeout(() => useAuthStore.getState().logout(), 0);
    return;
  }

  const refreshAt = Math.max(remaining - REFRESH_THRESHOLD_MS, 0);

  refreshTimer = setTimeout(async () => {
    try {
      const res = await api.auth.refresh();
      storeAuth(set, res);
      scheduleRefresh(set);
    } catch {
      toast("Your session has expired. Please log in again.", "error");
      useAuthStore.getState().logout();
    }
  }, refreshAt);
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: null,
  isLoading: false,
  error: null,

  login: async (email, password) => {
    set({ isLoading: true, error: null });
    try {
      storeAuth(set, await api.auth.login(email, password));
      scheduleRefresh(set);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Login failed";
      set({ error: msg, isLoading: false });
      toast(msg, "error");
    }
  },

  register: async (email, password, displayName) => {
    set({ isLoading: true, error: null });
    try {
      storeAuth(set, await api.auth.register(email, password, displayName));
      scheduleRefresh(set);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Registration failed";
      set({ error: msg, isLoading: false });
      toast(msg, "error");
    }
  },

  googleLogin: async (credential, nonce, csrfToken) => {
    set({ isLoading: true, error: null });
    try {
      storeAuth(set, await api.auth.googleLogin(credential, nonce, csrfToken));
      scheduleRefresh(set);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Google sign-in failed";
      set({ error: msg, isLoading: false });
      toast(msg, "error");
    }
  },

  logout: () => {
    if (refreshTimer) {
      clearTimeout(refreshTimer);
      refreshTimer = null;
    }
    if (typeof window !== "undefined" && window.google?.accounts?.id) {
      window.google.accounts.id.disableAutoSelect();
    }
    storage.removeItem("auth_token");
    storage.removeItem("auth_user");
    storage.removeItem("active_project_id");
    storage.removeItem("active_connection_id");
    storage.removeItem("active_session_id");
    set({ user: null, token: null });
  },

  restore: async () => {
    if (typeof window === "undefined") return;
    const token = storage.getItem("auth_token");
    const userStr = storage.getItem("auth_user");
    if (token && userStr) {
      try {
        const expMs = getTokenExpMs(token);
        if (expMs && expMs < Date.now()) {
          storage.removeItem("auth_token");
          storage.removeItem("auth_user");
          return;
        }
        set({ user: JSON.parse(userStr), token });
        scheduleRefresh(set);

        try {
          const fresh = await api.auth.me();
          try { storage.setItem("auth_user", JSON.stringify(fresh)); } catch { /* quota */ }
          set({ user: fresh });
        } catch {
          storage.removeItem("auth_token");
          storage.removeItem("auth_user");
          set({ user: null, token: null });
        }
      } catch {
        storage.removeItem("auth_token");
        storage.removeItem("auth_user");
      }
    }
  },
}));
