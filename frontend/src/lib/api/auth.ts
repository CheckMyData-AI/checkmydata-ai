import { request } from "./_client";
import type { AuthResponse, AuthUser } from "./types";

export interface McpToken {
  id: string;
  name: string;
  token_prefix: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

export interface McpTokenIssued extends McpToken {
  // Plaintext token — returned only at creation, never again.
  token: string;
}

export const mcpTokens = {
  list: () => request<McpToken[]>("/auth/mcp-tokens"),
  create: (name: string, expiresInDays?: number | null) =>
    request<McpTokenIssued>("/auth/mcp-tokens", {
      method: "POST",
      body: JSON.stringify({
        name,
        expires_in_days: expiresInDays ?? null,
      }),
    }),
  revoke: (id: string) =>
    request<{ revoked: boolean }>(`/auth/mcp-tokens/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
};

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
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  me: () => request<AuthUser>("/auth/me"),
  deleteAccount: () => request<{ ok: boolean }>("/auth/account", { method: "DELETE" }),
  completeOnboarding: () =>
    request<{ ok: boolean }>("/auth/complete-onboarding", { method: "POST" }),
};
