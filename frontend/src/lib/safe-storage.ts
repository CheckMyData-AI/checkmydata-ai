/**
 * Safe wrappers for localStorage that handle Safari private browsing
 * and other environments where storage access throws.
 */

export function getItem(key: string): string | null {
  try {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function setItem(key: string, value: string): void {
  try {
    if (typeof window !== "undefined") {
      localStorage.setItem(key, value);
    }
  } catch {
    /* storage unavailable */
  }
}

export function removeItem(key: string): void {
  try {
    if (typeof window !== "undefined") {
      localStorage.removeItem(key);
    }
  } catch {
    /* storage unavailable */
  }
}
