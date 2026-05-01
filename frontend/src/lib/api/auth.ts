import { request } from "./_client";
import type { AuthResponse, AuthUser } from "./types";

export const auth = {
  register: (email: string, password: string, displayName?: string) =>
    request<AuthResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, display_name: displayName || "" }),
    }),
  login: (email: string, password: string) =>
    request<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  googleLogin: (credential: string, nonce?: string, csrfToken?: string) =>
    request<AuthResponse>("/auth/google", {
      method: "POST",
      body: JSON.stringify({ credential, nonce, g_csrf_token: csrfToken }),
    }),
  changePassword: (currentPassword: string, newPassword: string) =>
    request<{ ok: boolean }>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    }),
  refresh: () => request<AuthResponse>("/auth/refresh", { method: "POST" }),
  me: () => request<AuthUser>("/auth/me"),
  deleteAccount: () => request<{ ok: boolean }>("/auth/account", { method: "DELETE" }),
  completeOnboarding: () =>
    request<{ ok: boolean }>("/auth/complete-onboarding", { method: "POST" }),
};
