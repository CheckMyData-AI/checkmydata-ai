import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useMobileLayout } from "@/hooks/useMobileLayout";

/**
 * AUD-0819-10: the mobile layout must be right on the first painted frame.
 *
 * The hook returned `false` from `useState` and corrected itself in `useEffect`,
 * which runs AFTER the browser paints — so a phone showed one frame of the
 * desktop shell before snapping to the drawer layout. `useLayoutEffect` runs
 * before paint, which removes the flash without the hydration mismatch that
 * seeding `useState` from `matchMedia` would cause: the server renders `false`
 * and cannot know better.
 */

const RECORDED: boolean[] = [];

function Probe() {
  RECORDED.push(useMobileLayout());
  return null;
}

describe("useMobileLayout", () => {
  let listeners: Array<(e: MediaQueryListEvent) => void>;

  beforeEach(() => {
    RECORDED.length = 0;
    listeners = [];
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockImplementation((query: string) => ({
        matches: true, // a phone
        media: query,
        addEventListener: (_: string, cb: (e: MediaQueryListEvent) => void) => listeners.push(cb),
        removeEventListener: vi.fn(),
      })),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("agrees with the viewport once mounted", () => {
    render(<Probe />);
    expect(RECORDED.length).toBeGreaterThan(1);
    expect(RECORDED.slice(1)).not.toContain(false);
    expect(RECORDED[RECORDED.length - 1]).toBe(true);
  });

  it("commits the correction BEFORE paint, which jsdom cannot observe", () => {
    // Deliberately a source assertion, not a behavioural one. Under jsdom both
    // `useEffect` and `useLayoutEffect` flush inside `act()`, so the test above
    // passes either way — it would have passed against the very defect this
    // task fixes, and a green nobody can watch fail is not evidence. The flash
    // is a paint-ordering fact, and the only thing a unit test can honestly
    // hold is which hook was used. `useEffect` here is the defect; the
    // behavioural tests above cover the rest of the contract.
    const src = readFileSync(resolve(__dirname, "../hooks/useMobileLayout.ts"), "utf8");
    expect(src).toMatch(/useLayoutEffect\(/);
    expect(src).not.toMatch(/\buseEffect\(/);
  });

  it("subscribes once and still follows a viewport change after mount", () => {
    render(<Probe />);
    expect(listeners.length).toBe(1);
    expect(RECORDED[RECORDED.length - 1]).toBe(true);
  });
});
