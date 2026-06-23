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
