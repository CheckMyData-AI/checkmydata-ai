import { create } from "zustand";
import * as storage from "@/lib/safe-storage";

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "cmd_theme";

function getSystemTheme(): ResolvedTheme {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return "light";
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function resolve(pref: ThemePreference): ResolvedTheme {
  return pref === "system" ? getSystemTheme() : pref;
}

function applyClass(resolved: ResolvedTheme): void {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("dark", resolved === "dark");
}

function readStored(): ThemePreference {
  const v = storage.getItem(THEME_STORAGE_KEY);
  return v === "light" || v === "dark" || v === "system" ? v : "light"; // D1 default
}

interface ThemeState {
  theme: ThemePreference;
  resolvedTheme: ResolvedTheme;
  setTheme: (pref: ThemePreference) => void;
  initTheme: () => void;
  syncSystem: () => void;
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: "light",
  resolvedTheme: "light",
  setTheme: (pref) => {
    storage.setItem(THEME_STORAGE_KEY, pref);
    const resolved = resolve(pref);
    applyClass(resolved);
    set({ theme: pref, resolvedTheme: resolved });
  },
  initTheme: () => {
    const pref = readStored();
    const resolved = resolve(pref);
    applyClass(resolved);
    set({ theme: pref, resolvedTheme: resolved });
  },
  syncSystem: () => {
    if (get().theme !== "system") return;
    const resolved = getSystemTheme();
    applyClass(resolved);
    set({ resolvedTheme: resolved });
  },
}));
