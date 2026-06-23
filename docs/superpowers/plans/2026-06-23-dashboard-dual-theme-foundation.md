# Dashboard Dual-Theme Token Foundation — Implementation Plan (Phase 0 of 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the whole frontend themeable (light + dark) on one token contract, with a FOUC-safe `light | dark | system` toggle — light is the default for new users — without changing any per-component markup.

**Architecture:** Move raw color values out of Tailwind v4's static `@theme` into runtime CSS custom properties under `:root` (light) and `.dark` (dark). Re-declare the semantic tokens with `@theme inline` so every existing `bg-surface-*` / `text-text-*` utility resolves to the runtime var and tracks the active theme. A Zustand `theme-store` owns preference + resolution + persistence; a pre-paint inline script applies the `.dark` class before React hydrates; a `ThemeToggle` in the account menu lets users switch.

**Tech Stack:** Next.js 15 (App Router), React 19, Tailwind CSS v4, Zustand, Vitest + Testing Library + jsdom.

**Source spec:** `docs/superpowers/specs/2026-06-23-dashboard-ux-audit-redesign-design.md` (§3.2 dual-theme, D1 default-light).

## Global Constraints

- Tailwind v4 theming pattern (verified against current Tailwind docs): raw vars in `:root`/`.dark`, aliased via `@theme inline { --color-x: var(--x); }`; class-based dark via `@custom-variant dark (&:where(.dark, .dark *));`. Exact values copied verbatim from spec §3.2.
- Default theme for users with no stored preference = **light** (spec D1). Stored values: `light | dark | system`.
- Theme class strategy = `.dark` on `document.documentElement`. Storage key = `cmd_theme` via `@/lib/safe-storage`.
- No per-component hex anywhere — all colors route through tokens (the toggle must be total).
- A11y target WCAG AA in **both** themes; icon-only controls need `aria-label`; segmented control exposes pressed state.
- Tests live in `src/__tests__/`; run with `npx vitest run`. `asyncio_mode` n/a (frontend). `matchMedia` is **not** provided by jsdom — tests must stub it.
- Conventional commits; this Phase 0 is independently shippable behind no flag (additive; default behavior = light theme, same component markup).

---

### Task 1: theme-store (preference, resolution, persistence)

**Files:**
- Create: `frontend/src/stores/theme-store.ts`
- Test: `frontend/src/__tests__/theme-store.test.ts`

**Interfaces:**
- Consumes: `getItem`, `setItem` from `@/lib/safe-storage`.
- Produces:
  - `type ThemePreference = "light" | "dark" | "system"`
  - `type ResolvedTheme = "light" | "dark"`
  - `const THEME_STORAGE_KEY = "cmd_theme"`
  - `useThemeStore` (Zustand) with state `{ theme: ThemePreference; resolvedTheme: ResolvedTheme }` and actions `setTheme(pref: ThemePreference): void`, `initTheme(): void`, `syncSystem(): void`.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/__tests__/theme-store.test.ts
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/theme-store.test.ts`
Expected: FAIL — cannot resolve `@/stores/theme-store` / `useThemeStore is not defined`.

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/stores/theme-store.ts
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/theme-store.test.ts`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/theme-store.ts frontend/src/__tests__/theme-store.test.ts
git commit -m "feat(theme): theme-store with light/dark/system preference + resolution"
```

---

### Task 2: dual-theme token contract in globals.css

**Files:**
- Modify: `frontend/src/app/globals.css` (line 1 area, the `html, body` rule lines 3–8, and the `@theme { … }` + following `:root { ease }` block lines 31–74)
- Test: `frontend/src/__tests__/theme-tokens.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: runtime CSS vars `--surface-0..3`, `--border-subtle/default`, `--text-primary/secondary/tertiary/muted`, `--accent*`, `--success/warning/error/info(+ -muted)` defined in `:root` (light) and `.dark` (dark); `@theme inline` aliases `--color-*` → these. No new JS exports.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/__tests__/theme-tokens.test.ts
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(__dirname, "../app/globals.css"), "utf8");

describe("globals.css dual-theme contract", () => {
  it("registers a class-based dark variant", () => {
    expect(css).toMatch(/@custom-variant dark \(&:where\(\.dark, \.dark \*\)\)/);
  });
  it("aliases color tokens via @theme inline", () => {
    expect(css).toMatch(/@theme inline\s*\{/);
    expect(css).toMatch(/--color-surface-0:\s*var\(--surface-0\)/);
    expect(css).toMatch(/--color-text-primary:\s*var\(--text-primary\)/);
  });
  it("defines a light :root palette and a .dark override", () => {
    expect(css).toMatch(/:root\s*\{[^}]*--surface-0:\s*#fafafa/s);
    expect(css).toMatch(/\.dark\s*\{[^}]*--surface-0:\s*#09090b/s);
  });
  it("does not hardcode a dark body background", () => {
    expect(css).not.toMatch(/background-color:\s*#09090b/);
    expect(css).toMatch(/html,\s*body\s*\{[^}]*background-color:\s*var\(--surface-0\)/s);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/theme-tokens.test.ts`
Expected: FAIL — current file hardcodes `#09090b` on body and uses static `@theme {`.

- [ ] **Step 3a: Add the dark variant after the Tailwind import**

Change line 1–2 of `frontend/src/app/globals.css` from:

```css
@import "tailwindcss";

```
to:

```css
@import "tailwindcss";

@custom-variant dark (&:where(.dark, .dark *));

```

- [ ] **Step 3b: Stop hardcoding the body background**

In the `html, body { … }` rule, replace `background-color: #09090b;` with:

```css
  background-color: var(--surface-0);
```

- [ ] **Step 3c: Replace the static `@theme { … }` block and the duplicate `:root { ease }` block**

Replace the entire block that begins at `@theme {` and ends at the close of the `:root { --ease-* }` rule (the `.ease-out-quart { … }` utility classes below it stay untouched) with:

```css
@theme inline {
  --font-sans: var(--font-sans), ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-mono), ui-monospace, monospace;
  --font-display: var(--font-display), var(--font-sans), ui-sans-serif, system-ui, sans-serif;

  --color-surface-0: var(--surface-0);
  --color-surface-1: var(--surface-1);
  --color-surface-2: var(--surface-2);
  --color-surface-3: var(--surface-3);

  --color-border-subtle: var(--border-subtle);
  --color-border-default: var(--border-default);

  --color-text-primary: var(--text-primary);
  --color-text-secondary: var(--text-secondary);
  --color-text-tertiary: var(--text-tertiary);
  --color-text-muted: var(--text-muted);

  --color-accent: var(--accent);
  --color-accent-hover: var(--accent-hover);
  --color-accent-strong: var(--accent-strong);
  --color-accent-muted: var(--accent-muted);

  --color-success: var(--success);
  --color-success-muted: var(--success-muted);
  --color-warning: var(--warning);
  --color-warning-muted: var(--warning-muted);
  --color-error: var(--error);
  --color-error-hover: var(--error-hover);
  --color-error-muted: var(--error-muted);
  --color-info: var(--info);
  --color-info-muted: var(--info-muted);

  --ease-out-quart: cubic-bezier(0.23, 1, 0.32, 1);
  --ease-in-out-strong: cubic-bezier(0.77, 0, 0.175, 1);
  --ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);
}

:root {
  /* LIGHT — airy default for new users (spec D1) */
  --surface-0: #fafafa;
  --surface-1: #ffffff;
  --surface-2: #f4f4f5;
  --surface-3: #e4e4e7;
  --border-subtle: #e4e4e7;
  --border-default: #d4d4d8;
  --text-primary: #18181b;
  --text-secondary: #52525b;
  --text-tertiary: #71717a;
  --text-muted: #a1a1aa;
  --accent: #2563eb;
  --accent-hover: #3b82f6;
  --accent-strong: #1d4ed8;
  --accent-muted: #2563eb14;
  --success: #059669;
  --success-muted: #05966914;
  --warning: #d97706;
  --warning-muted: #d9770614;
  --error: #dc2626;
  --error-hover: #ef4444;
  --error-muted: #dc262614;
  --info: #2563eb;
  --info-muted: #2563eb14;

  --ease-out-quart: cubic-bezier(0.23, 1, 0.32, 1);
  --ease-in-out-strong: cubic-bezier(0.77, 0, 0.175, 1);
  --ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);
}

.dark {
  /* DARK — current values preserved verbatim */
  --surface-0: #09090b;
  --surface-1: #18181b;
  --surface-2: #27272a;
  --surface-3: #3f3f46;
  --border-subtle: #27272a;
  --border-default: #3f3f46;
  --text-primary: #fafafa;
  --text-secondary: #a1a1aa;
  --text-tertiary: #84848e;
  --text-muted: #52525b;
  --accent: #3b82f6;
  --accent-hover: #60a5fa;
  --accent-strong: #1d4ed8;
  --accent-muted: #3b82f620;
  --success: #34d399;
  --success-muted: #34d39920;
  --warning: #fbbf24;
  --warning-muted: #fbbf2420;
  --error: #f87171;
  --error-hover: #fca5a5;
  --error-muted: #f8717120;
  --info: #60a5fa;
  --info-muted: #60a5fa20;
}
```

- [ ] **Step 4a: Run the contract test**

Run: `cd frontend && npx vitest run src/__tests__/theme-tokens.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 4b: Verify the production build compiles the CSS**

Run: `cd frontend && npx next build` (or `npm run build`)
Expected: build completes with no CSS/PostCSS errors.

- [ ] **Step 4c: Manual visual check**

Run `npm run dev`, open `http://localhost:3100`. In devtools toggle `class="dark"` on `<html>`: surfaces/text must flip between the light and dark palettes; with `.dark` absent the canvas is `#fafafa`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/globals.css frontend/src/__tests__/theme-tokens.test.ts
git commit -m "feat(theme): runtime dual-theme token contract (@theme inline + :root/.dark)"
```

---

### Task 3: FOUC-safe pre-paint script + ThemeWatcher + layout wiring

**Files:**
- Create: `frontend/src/components/theme/ThemeWatcher.tsx`
- Modify: `frontend/src/app/layout.tsx` (`<html lang="en">` at line 92, `<body>` at line 93)
- Test: `frontend/src/__tests__/ThemeWatcher.test.tsx`

**Interfaces:**
- Consumes: `useThemeStore` (`initTheme`, `syncSystem`), `THEME_STORAGE_KEY` from Task 1.
- Produces: `ThemeWatcher` (default-less named export, renders `null`). No new types.

- [ ] **Step 1: Write the failing test**

```tsx
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/ThemeWatcher.test.tsx`
Expected: FAIL — cannot resolve `@/components/theme/ThemeWatcher`.

- [ ] **Step 3a: Implement ThemeWatcher**

```tsx
// frontend/src/components/theme/ThemeWatcher.tsx
"use client";

import { useEffect } from "react";
import { useThemeStore } from "@/stores/theme-store";

export function ThemeWatcher() {
  useEffect(() => {
    useThemeStore.getState().initTheme();

    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => useThemeStore.getState().syncSystem();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  return null;
}
```

- [ ] **Step 3b: Wire the pre-paint script and ThemeWatcher into the root layout**

In `frontend/src/app/layout.tsx`:

1. Add the import near the other imports:

```tsx
import { THEME_STORAGE_KEY } from "@/stores/theme-store";
import { ThemeWatcher } from "@/components/theme/ThemeWatcher";
```

2. Above the component's `return`, define the script (interpolating the shared key so it never drifts from the store):

```tsx
  const themeScript = `(function(){try{var k='${THEME_STORAGE_KEY}';var t=localStorage.getItem(k)||'light';var d=t==='dark'||(t==='system'&&window.matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.classList.toggle('dark',d);}catch(e){}})();`;
```

3. Add `suppressHydrationWarning` to the `<html>` tag (we mutate its class before hydration) and render the script + watcher as the first children of `<body>`:

```tsx
    <html lang="en" suppressHydrationWarning>
      <body className={`${dmSans.variable} ${jetbrainsMono.variable} ${spaceGrotesk.variable} font-sans antialiased`}>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <ThemeWatcher />
        <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:z-[100] focus:top-2 focus:left-2 focus:px-4 focus:py-2 focus:bg-accent focus:text-white focus:rounded-lg focus:text-sm">
```

(Leave the rest of `<body>` unchanged.)

- [ ] **Step 4a: Run the watcher test**

Run: `cd frontend && npx vitest run src/__tests__/ThemeWatcher.test.tsx`
Expected: PASS.

- [ ] **Step 4b: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4c: Manual FOUC check**

`npm run dev`; set theme to dark (devtools: `localStorage.setItem('cmd_theme','dark')`), hard-reload — there must be **no** white flash before dark paints. Repeat with `'light'` and `'system'`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/theme/ThemeWatcher.tsx frontend/src/app/layout.tsx frontend/src/__tests__/ThemeWatcher.test.tsx
git commit -m "feat(theme): FOUC-safe pre-paint theme script + ThemeWatcher in root layout"
```

---

### Task 4: ThemeToggle control + account-menu wiring

**Files:**
- Create: `frontend/src/components/theme/ThemeToggle.tsx`
- Modify: `frontend/src/components/auth/AccountMenu.tsx` (the `view === "menu"` block, around lines 64–92)
- Test: `frontend/src/__tests__/ThemeToggle.test.tsx`

**Interfaces:**
- Consumes: `useThemeStore` (`theme`, `setTheme`), `ThemePreference` from Task 1.
- Produces: `ThemeToggle` named export — a 3-option segmented control (`light | system | dark`) with self-contained inline SVG icons (no dependency on `Icon.tsx`).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/__tests__/ThemeToggle.test.tsx
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { useThemeStore } from "@/stores/theme-store";

afterEach(cleanup);
beforeEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
  useThemeStore.setState({ theme: "light", resolvedTheme: "light" });
});

describe("ThemeToggle", () => {
  it("renders an accessible group with three options", () => {
    render(<ThemeToggle />);
    expect(screen.getByRole("group", { name: /theme/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /light/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /system/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /dark/i })).toBeInTheDocument();
  });

  it("marks the active preference with aria-pressed", () => {
    useThemeStore.setState({ theme: "light", resolvedTheme: "light" });
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: /light/i })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /dark/i })).toHaveAttribute("aria-pressed", "false");
  });

  it("switches preference on click", () => {
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button", { name: /dark/i }));
    expect(useThemeStore.getState().theme).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/ThemeToggle.test.tsx`
Expected: FAIL — cannot resolve `@/components/theme/ThemeToggle`.

- [ ] **Step 3a: Implement ThemeToggle**

```tsx
// frontend/src/components/theme/ThemeToggle.tsx
"use client";

import { useThemeStore, type ThemePreference } from "@/stores/theme-store";

const ICONS: Record<ThemePreference, React.ReactNode> = {
  light: (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
    </svg>
  ),
  system: (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="2" y="3" width="20" height="14" rx="2" />
      <path d="M8 21h8M12 17v4" />
    </svg>
  ),
  dark: (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  ),
};

const OPTIONS: { value: ThemePreference; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "system", label: "System" },
  { value: "dark", label: "Dark" },
];

export function ThemeToggle() {
  const theme = useThemeStore((s) => s.theme);
  const setTheme = useThemeStore((s) => s.setTheme);

  return (
    <div
      role="group"
      aria-label="Theme"
      className="flex items-center gap-1 rounded-lg border border-border-subtle bg-surface-1 p-0.5"
    >
      {OPTIONS.map((opt) => {
        const active = theme === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => setTheme(opt.value)}
            aria-label={opt.label}
            aria-pressed={active}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent ${
              active
                ? "bg-accent-muted text-accent"
                : "text-text-tertiary hover:text-text-secondary hover:bg-surface-2"
            }`}
          >
            {ICONS[opt.value]}
            <span>{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 3b: Mount ThemeToggle in the account menu**

In `frontend/src/components/auth/AccountMenu.tsx`, add the import:

```tsx
import { ThemeToggle } from "@/components/theme/ThemeToggle";
```

Inside the `view === "menu"` block, render the toggle above the "Sign Out" button (wrap it so it reads as a labelled row):

```tsx
                <div className="px-2.5 py-2 border-b border-border-subtle">
                  <p className="text-[10px] uppercase tracking-wider text-text-muted mb-1.5">Appearance</p>
                  <ThemeToggle />
                </div>
```

- [ ] **Step 4a: Run the toggle test**

Run: `cd frontend && npx vitest run src/__tests__/ThemeToggle.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 4b: Full frontend gate (CI parity)**

Run: `cd frontend && npx tsc --noEmit && npx eslint . --max-warnings=0 && npx vitest run`
Expected: typecheck clean, no lint warnings, all tests pass.

- [ ] **Step 4c: Manual check**

`npm run dev`, open the account menu → the Appearance segmented control switches the whole app light/system/dark; reload preserves the choice; the active option shows the accent state.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/theme/ThemeToggle.tsx frontend/src/components/auth/AccountMenu.tsx frontend/src/__tests__/ThemeToggle.test.tsx
git commit -m "feat(theme): light/system/dark toggle in the account menu"
```

---

## Self-review

**Spec coverage (spec §3.2 + D1):** runtime token contract via `@theme inline` + `:root`/`.dark` (Task 2) ✓; `light | dark | system` toggle (Task 4) ✓; FOUC-safe + system-aware + persisted, default light for new users (Tasks 1+3, D1) ✓; existing `bg-surface-*`/`text-text-*` utilities unchanged (alias pattern, Task 2) ✓; charts theme-aware and full surface restyle are **later phases** (Phases 2/6) — out of Phase 0 scope by design.

**Placeholder scan:** none — every code/test block is complete; commands have expected output.

**Type consistency:** `ThemePreference`/`ResolvedTheme`/`THEME_STORAGE_KEY`/`useThemeStore` actions (`setTheme`, `initTheme`, `syncSystem`) are defined in Task 1 and consumed verbatim in Tasks 3 and 4. `ThemeToggle`/`ThemeWatcher` are named exports consumed exactly as produced.

**Scope note:** this is **Phase 0 of 6** from spec §9. Phases 1–5 (activation funnel, Ask-home + calm answer, role-adaptive shell, Workspace hub, `/admin` console) each get their own plan; Phase 6 (motion/a11y/charts/KPIs) closes out. Phase 0 is the contracts-first enabler and ships independently with no behavior change beyond theme availability (default light).
