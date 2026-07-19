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
  // F-PROJ-01: public endpoint — confirms an email address from the emailed link.
  verifyEmail: (token: string) =>
    request<{ ok: boolean; invites_accepted: number }>("/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),
  // Re-sends the verification email for the signed-in user. No-op (already_verified:
  // true) for Google or already-verified accounts.
  resendVerification: () =>
    request<{ ok: boolean; already_verified: boolean }>("/auth/resend-verification", {
      method: "POST",
    }),
  // SCN-013: public endpoints. forgot-password always resolves to {ok:true} (the
  // backend never reveals whether the address exists); reset-password rejects an
  // invalid/expired token with a 4xx surfaced as a thrown Error.
  forgotPassword: (email: string) =>
    request<{ ok: boolean }>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  resetPassword: (token: string, newPassword: string) =>
    request<{ ok: boolean }>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, new_password: newPassword }),
    }),
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  me: () => request<AuthUser>("/auth/me"),
  deleteAccount: () => request<{ ok: boolean }>("/auth/account", { method: "DELETE" }),
  completeOnboarding: () =>
    request<{ ok: boolean }>("/auth/complete-onboarding", { method: "POST" }),
};
