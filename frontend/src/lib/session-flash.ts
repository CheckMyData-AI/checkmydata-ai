/**
 * Session-expiry flash message (FA-010).
 *
 * The 401 interceptor redirects with `window.location.href = "/login"`, which
 * unloads the document and kills any in-memory toast. The message is therefore
 * stashed in sessionStorage right before the redirect and consumed exactly
 * once by the login page.
 */

/** Single source of truth for the session-expired user message (SCN-011, M2). */
export const SESSION_EXPIRED_MESSAGE =
  "Your session has expired. Please log in again.";

const FLASH_KEY = "cmd_session_flash";

export function setSessionFlash(message: string): void {
  try {
    if (typeof window !== "undefined") {
      sessionStorage.setItem(FLASH_KEY, message);
    }
  } catch {
    /* storage unavailable */
  }
}

/** Read the flash once and clear it — it must surface exactly one time. */
export function consumeSessionFlash(): string | null {
  try {
    if (typeof window === "undefined") return null;
    const message = sessionStorage.getItem(FLASH_KEY);
    if (message) sessionStorage.removeItem(FLASH_KEY);
    return message;
  } catch {
    return null;
  }
}
