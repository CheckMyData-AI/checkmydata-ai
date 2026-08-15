// frontend/src/__tests__/theme-tokens.test.ts
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(__dirname, "../app/globals.css"), "utf8");

/** The verbatim `ledger` token block, from its opening comment to the reduced-motion reset. */
const TOKEN_BLOCK = css.slice(
  css.indexOf("/* SHELEG Design — Ledger token layer"),
  css.indexOf("Compatibility layer"),
);

/** Everything this project wrote itself: the aliases, the theme block, the utilities. */
const PROJECT_CSS = css.slice(css.indexOf("Compatibility layer"));

describe("globals.css dual-theme contract", () => {
  it("registers a class-based dark variant", () => {
    expect(css).toMatch(/@custom-variant dark \(&:where\(\.dark, \.dark \*\)\)/);
  });

  it("aliases color tokens via @theme inline", () => {
    expect(css).toMatch(/@theme inline\s*\{/);
    expect(css).toMatch(/--color-surface-0:\s*var\(--surface-0\)/);
    expect(css).toMatch(/--color-text-primary:\s*var\(--text-primary\)/);
  });

  it("ships a light default and a dark twin that redeclares the field and the ink", () => {
    // The pack's own selector, which is why theme-store sets data-theme as well
    // as the class. Both halves must declare the two tokens every pack resolves.
    expect(TOKEN_BLOCK).toMatch(/:root\s*\{[\s\S]*?--bg:[\s\S]*?--ink:/);
    const dark = TOKEN_BLOCK.slice(TOKEN_BLOCK.indexOf('[data-theme="dark"]'));
    expect(dark).toMatch(/--bg:/);
    expect(dark).toMatch(/--ink:/);
  });

  it("resolves every project-authored colour through a token, never a literal", () => {
    // The pack layer is the only place a hex may appear. A literal below it is
    // a value that stops tracking the theme the moment either half moves — the
    // exact defect the token layer exists to prevent.
    const literals = PROJECT_CSS.split("\n")
      .filter((line) => !line.trimStart().startsWith("*") && !line.trimStart().startsWith("/*"))
      .filter((line) => /#[0-9a-fA-F]{3,8}\b/.test(line))
      // The cinematic marketing layer is a separate system and out of this scope.
      .filter((line) => !/cmd-|marketing/.test(line))
      // A mask reads alpha only — its colour is not a theme value and `#000`
      // there means "fully opaque", in every theme.
      .filter((line) => !/mask-image/.test(line));
    expect(literals).toEqual([]);
  });

  it("takes the body background from a token", () => {
    expect(css).toMatch(/html,\s*body\s*\{[\s\S]*?background-color:\s*var\(--bg\)/);
  });

  it("gives shadcn's contract the pack's meanings, with INK as the primary fill", () => {
    // The pack forbids the accent from filling a control. If --primary ever
    // points at --accent, every shadcn button in the app turns orange and the
    // pack's one rule about its accent is gone.
    expect(PROJECT_CSS).toMatch(/--primary:\s*var\(--ink\)/);
    expect(PROJECT_CSS).toMatch(/--primary-foreground:\s*var\(--on-ink\)/);
    expect(PROJECT_CSS).toMatch(/--ring:\s*var\(--accent\)/);
  });

  it("exposes the chart ramp under the names a shadcn ChartConfig reads", () => {
    for (const n of [1, 2, 3, 4, 5]) {
      expect(css).toMatch(new RegExp(`--chart-${n}:`));
      expect(PROJECT_CSS).toMatch(new RegExp(`--color-chart-${n}:\\s*var\\(--chart-${n}\\)`));
    }
  });
});
