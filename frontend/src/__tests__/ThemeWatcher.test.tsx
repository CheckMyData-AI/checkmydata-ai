// frontend/src/__tests__/ThemeWatcher.test.tsx
import { render, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThemeWatcher } from "@/components/theme/ThemeWatcher";
import { useThemeStore } from "@/stores/theme-store";

afterEach(cleanup);

describe("ThemeWatcher", () => {
  it("initialises the theme on mount and subscribes to system changes", () => {
    const initTheme = vi.spyOn(useThemeStore.getState(), "initTheme");
    const addEventListener = vi.fn();
    const removeEventListener = vi.fn();
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockReturnValue({
        matches: false,
        addEventListener,
        removeEventListener,
        addListener: vi.fn(),
        removeListener: vi.fn(),
      }),
    });

    const { unmount } = render(<ThemeWatcher />);
    expect(initTheme).toHaveBeenCalledTimes(1);
    expect(addEventListener).toHaveBeenCalledWith("change", expect.any(Function));

    unmount();
    expect(removeEventListener).toHaveBeenCalledWith("change", expect.any(Function));
  });
});
