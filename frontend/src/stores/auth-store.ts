import { create } from "zustand";
import { api, type AuthUser } from "@/lib/api";

interface AuthState {
  user: AuthUser | null;
  token: string | null;
  isLoading: boolean;
  error: string | null;

  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName?: string) => Promise<void>;
  googleLogin: (credential: string) => Promise<void>;
  logout: () => void;
  restore: () => void;
}

function storeAuth(set: (s: Partial<AuthState>) => void, res: { token: string; user: AuthUser }) {
  localStorage.setItem("auth_token", res.token);
  localStorage.setItem("auth_user", JSON.stringify(res.user));
  set({ user: res.user, token: res.token, isLoading: false });
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
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Login failed", isLoading: false });
    }
  },

  register: async (email, password, displayName) => {
    set({ isLoading: true, error: null });
    try {
      storeAuth(set, await api.auth.register(email, password, displayName));
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Registration failed", isLoading: false });
    }
  },

  googleLogin: async (credential) => {
    set({ isLoading: true, error: null });
    try {
      storeAuth(set, await api.auth.googleLogin(credential));
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Google sign-in failed", isLoading: false });
    }
  },

  logout: () => {
    localStorage.removeItem("auth_token");
    localStorage.removeItem("auth_user");
    set({ user: null, token: null });
  },

  restore: () => {
    if (typeof window === "undefined") return;
    const token = localStorage.getItem("auth_token");
    const userStr = localStorage.getItem("auth_user");
    if (token && userStr) {
      try {
        set({ user: JSON.parse(userStr), token });
      } catch {
        localStorage.removeItem("auth_token");
        localStorage.removeItem("auth_user");
      }
    }
  },
}));
