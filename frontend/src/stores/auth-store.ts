import { create } from "zustand";
import { api, resetSessionExpiredFlag, type AuthUser } from "@/lib/api";
import * as storage from "@/lib/safe-storage";
import { SESSION_EXPIRED_MESSAGE } from "@/lib/session-flash";
import { toast } from "@/stores/toast-store";
import { useAppStore } from "@/stores/app-store";
import { useNotesStore } from "@/stores/notes-store";
import { useLogStore } from "@/stores/log-store";
import { useBackgroundTasks } from "@/stores/background-tasks-store";

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

// T-SEC-3: the JWT now lives in an httpOnly cookie the browser cannot read.
// We persist only the non-sensitive user profile for instant UI paint, and keep
// the token in memory solely to schedule a proactive refresh before expiry.
function storeAuth(set: (s: Partial<AuthState>) => void, res: { token: string; user: AuthUser }) {
  try {
    storage.setItem("auth_user", JSON.stringify(res.user));
  } catch {
    /* storage quota / unavailable */
  }
  // Successful (re-)authentication re-arms the one-shot 401 handler (M1).
  resetSessionExpiredFlag();
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

function scheduleRefresh(
  set: (s: Partial<AuthState>) => void,
  res: { token: string | null; expires_in?: number },
) {
  if (refreshTimer) clearTimeout(refreshTimer);

  // Prefer the server-provided lifetime (works under cookie auth where the token
  // body is empty — F-AUTH-04); fall back to decoding the JWT for Bearer clients.
  let expMs: number | null = null;
  if (res.expires_in && res.expires_in > 0) {
    expMs = Date.now() + res.expires_in * 1000;
  } else if (res.token) {
    expMs = getTokenExpMs(res.token);
  }
  if (!expMs) return;

  const remaining = expMs - Date.now();
  if (remaining <= 0) {
    toast(SESSION_EXPIRED_MESSAGE, "error");
    setTimeout(() => useAuthStore.getState().logout(), 0);
    return;
  }

  const refreshAt = Math.max(remaining - REFRESH_THRESHOLD_MS, 0);

  refreshTimer = setTimeout(async () => {
    try {
      const res = await api.auth.refresh();
      storeAuth(set, res);
      scheduleRefresh(set, res);
    } catch {
      toast(SESSION_EXPIRED_MESSAGE, "error");
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
      const res = await api.auth.login(email, password);
      storeAuth(set, res);
      scheduleRefresh(set, res);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Login failed";
      set({ error: msg, isLoading: false });
      toast(msg, "error");
    }
  },

  register: async (email, password, displayName) => {
    set({ isLoading: true, error: null });
    try {
      const res = await api.auth.register(email, password, displayName);
      storeAuth(set, res);
      scheduleRefresh(set, res);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Registration failed";
      set({ error: msg, isLoading: false });
      toast(msg, "error");
    }
  },

  googleLogin: async (credential, nonce, csrfToken) => {
    set({ isLoading: true, error: null });
    try {
      const res = await api.auth.googleLogin(credential, nonce, csrfToken);
      storeAuth(set, res);
      scheduleRefresh(set, res);
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
    // Clear the httpOnly session + CSRF cookies server-side (best effort).
    void api.auth.logout().catch(() => {});
    storage.removeItem("auth_token");
    storage.removeItem("auth_user");
    storage.removeItem("active_project_id");
    storage.removeItem("active_connection_id");
    storage.removeItem("active_session_id");

    const appStore = useAppStore.getState();
    appStore.clearAllSessionMessages();
    appStore.clearToolCalls();
    appStore.setActiveProject(null);
    appStore.setActiveConnection(null);
    appStore.setActiveSession(null);
    appStore.setProjects([]);
    appStore.setConnections([]);
    appStore.setConnectionsError(null);
    appStore.setChatSessions([]);
    appStore.setSshKeys([]);
    appStore.resetSessionUsage();
    appStore.setRestoringState(false);

    useNotesStore.getState().clear();
    useLogStore.getState().clear();
    useBackgroundTasks.setState({ tasks: {}, pinnedRunningIds: new Set() });

    set({ user: null, token: null });
  },

  restore: async () => {
    if (typeof window === "undefined") return;
    // Optimistic paint from the cached (non-sensitive) profile, then validate
    // the session against the httpOnly cookie via a refresh. The refresh rotates
    // the token and returns a fresh exp we can schedule against; no token is
    // ever read from storage (T-SEC-3).
    const userStr = storage.getItem("auth_user");
    if (userStr) {
      try {
        set({ user: JSON.parse(userStr) });
      } catch {
        storage.removeItem("auth_user");
      }
    }

    try {
      const res = await api.auth.refresh();
      storeAuth(set, res);
      scheduleRefresh(set, res);
    } catch {
      storage.removeItem("auth_token");
      storage.removeItem("auth_user");
      set({ user: null, token: null });
    }
  },
}));
