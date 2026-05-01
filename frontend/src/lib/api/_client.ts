import { toast } from "@/stores/toast-store";
import { useAuthStore } from "@/stores/auth-store";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

let sessionExpiredHandled = false;

export function handleSessionExpired(): void {
  if (sessionExpiredHandled || typeof window === "undefined") return;
  sessionExpiredHandled = true;
  useAuthStore.getState().logout();
  toast("Session expired, please log in again", "error");
  window.location.href = "/login";
}

export function getAuthHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const token = localStorage.getItem("auth_token");
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

const DEFAULT_TIMEOUT_MS = 60_000;
const MAX_RETRIES = 2;
const RETRY_BACKOFF_MS = [600, 1500];
const RETRYABLE_STATUSES = new Set([502, 503, 504]);

function isSafeMethod(method?: string): boolean {
  return (
    !method ||
    method.toUpperCase() === "GET" ||
    method.toUpperCase() === "HEAD"
  );
}

export async function request<T>(
  path: string,
  options?: RequestInit & { timeoutMs?: number },
): Promise<T> {
  const { headers: optHeaders, timeoutMs, ...restOptions } = (options ?? {}) as RequestInit & { timeoutMs?: number };
  const safe = isSafeMethod(restOptions.method);
  let lastError: Error | undefined;

  for (let attempt = 0; attempt <= (safe ? MAX_RETRIES : 0); attempt++) {
    if (attempt > 0) {
      await new Promise((r) => setTimeout(r, RETRY_BACKOFF_MS[attempt - 1] ?? 1500));
    }

    const controller = new AbortController();
    const existingSignal = restOptions.signal;
    let onAbort: (() => void) | undefined;
    if (existingSignal) {
      if (existingSignal.aborted) throw new Error("Request aborted");
      onAbort = () => controller.abort(existingSignal.reason);
      existingSignal.addEventListener("abort", onAbort);
    }
    const timeout = setTimeout(() => controller.abort("Request timed out"), timeoutMs ?? DEFAULT_TIMEOUT_MS);

    let res: Response;
    try {
      res = await fetch(`${API_BASE}${path}`, {
        ...restOptions,
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeaders(),
          ...(optHeaders instanceof Headers
            ? Object.fromEntries(optHeaders.entries())
            : Array.isArray(optHeaders)
              ? Object.fromEntries(optHeaders)
              : optHeaders),
        },
      });
    } catch (err) {
      clearTimeout(timeout);
      if (existingSignal && onAbort) existingSignal.removeEventListener("abort", onAbort);
      if (err instanceof DOMException && err.name === "AbortError") {
        throw new Error("Request timed out. Please try again.");
      }
      lastError = err instanceof Error ? err : new Error(String(err));
      if (safe && attempt < MAX_RETRIES) continue;
      throw lastError;
    }
    clearTimeout(timeout);
    if (existingSignal && onAbort) existingSignal.removeEventListener("abort", onAbort);

    if (safe && RETRYABLE_STATUSES.has(res.status) && attempt < MAX_RETRIES) {
      lastError = new Error(`Request failed: ${res.status}`);
      continue;
    }

    if (!res.ok) {
      const isAuthRoute = path.startsWith("/auth/");
      if (res.status === 401 && !isAuthRoute && typeof window !== "undefined") {
        handleSessionExpired();
        throw new Error("Session expired. Please log in again.");
      }
      if (res.status === 403) {
        throw new Error("You don't have permission to perform this action.");
      }
      if (res.status === 429) {
        throw new Error("Too many requests. Please wait a moment and try again.");
      }
      const body = await res.json().catch(() => ({}));
      const detail = Array.isArray(body.detail)
        ? body.detail.map((e: { msg?: string; message?: string }) => e.msg ?? e.message ?? "Validation error").join("; ")
        : body.detail || `Request failed: ${res.status}`;
      throw new Error(detail);
    }
    return res.json();
  }
  throw lastError ?? new Error("Request failed after retries");
}
