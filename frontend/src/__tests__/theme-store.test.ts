import { beforeEach, describe, expect, it, vi } from "vitest";
import { THEME_STORAGE_KEY, useThemeStore } from "@/stores/theme-store";

function mockMatchMedia(dark: boolean) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: dark,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      onchange: null,
      dispatchEvent: vi.fn(),
    })),
  });
}

describe("theme-store", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark");
    mockMatchMedia(false);
    useThemeStore.setState({ theme: "light", resolvedTheme: "light" });
  });

  it("defaults to light when nothing is stored (D1)", () => {
    useThemeStore.getState().initTheme();
    expect(useThemeStore.getState().theme).toBe("light");
    expect(useThemeStore.getState().resolvedTheme).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("setTheme('dark') applies the .dark class and persists", () => {
    useThemeStore.getState().setTheme("dark");
    expect(useThemeStore.getState().resolvedTheme).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });

  it("setTheme('system') resolves to the OS preference", () => {
    mockMatchMedia(true);
    useThemeStore.getState().setTheme("system");
    expect(useThemeStore.getState().theme).toBe("system");
    expect(useThemeStore.getState().resolvedTheme).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("initTheme reads a stored preference and applies it", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    useThemeStore.getState().initTheme();
    expect(useThemeStore.getState().resolvedTheme).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("syncSystem updates resolvedTheme only while preference is 'system'", () => {
    useThemeStore.getState().setTheme("light");
    mockMatchMedia(true);
    useThemeStore.getState().syncSystem();
    expect(useThemeStore.getState().resolvedTheme).toBe("light"); // pref is light, ignore OS
    useThemeStore.getState().setTheme("system");
    useThemeStore.getState().syncSystem();
    expect(useThemeStore.getState().resolvedTheme).toBe("dark");
  });
});
