import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The `ledger` pack's bans, as a ratchet rather than a good intention.
 *
 * A design rule that lives only in a document is obeyed until the first hurried
 * change. These are the two that decide whether a screen still reads as this
 * design, and both are mechanically checkable, so they are checked.
 */

const SRC = resolve(__dirname, "..");

function tsxFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) {
      if (entry === "__tests__" || entry === "node_modules") continue;
      tsxFiles(p, out);
    } else if (entry.endsWith(".tsx")) {
      out.push(p);
    }
  }
  return out;
}

const FILES = tsxFiles(SRC).map((p) => ({ path: relative(SRC, p), lines: readFileSync(p, "utf8").split("\n") }));

/** `bg-accent` next to a foreground meant to sit ON a fill = a filled control. */
const FILLED_CONTROL = /\bbg-accent\b(?!-)/;
const ON_FILL_TEXT = /\btext-(white|primary-foreground|on-ink)\b/;
const ACCENT_GRADIENT = /\b(?:from|via|to)-accent(?:-strong|-hover|-mark)?\b/;

describe("ledger pack bans", () => {
  it("never fills a control with the accent — the accent labels and marks", () => {
    const offenders = FILES.flatMap(({ path, lines }) =>
      lines
        .map((line, i) => ({ line, i }))
        .filter(({ line }) => FILLED_CONTROL.test(line) && ON_FILL_TEXT.test(line))
        .map(({ i }) => `${path}:${i + 1}`),
    );
    expect(offenders).toEqual([]);
  });

  it("never paints a gradient in the accent — the pack has no gradient surface", () => {
    const offenders = FILES.flatMap(({ path, lines }) =>
      lines
        .map((line, i) => ({ line, i }))
        .filter(({ line }) => /bg-gradient/.test(line) && ACCENT_GRADIENT.test(line))
        .map(({ i }) => `${path}:${i + 1}`),
    );
    expect(offenders).toEqual([]);
  });

  it("keeps the shadcn layer off shadcn's own accent and muted SURFACES", () => {
    // In this project `--accent` is the brand terracotta and `--muted` is muted
    // ink; shadcn means a hover surface and a surface fill by those names. A
    // component copied in from the registry without re-theming brings the
    // collision with it, and the failure is silent: an orange menu row.
    const shadcn = FILES.filter((f) => f.path.startsWith("components/shadcn/"));
    expect(shadcn.length).toBeGreaterThan(10);
    const offenders = shadcn.flatMap(({ path, lines }) =>
      lines
        .map((line, i) => ({ line, i }))
        .filter(({ line }) => /\b(bg-accent|text-accent-foreground|bg-muted)\b/.test(line))
        .map(({ i }) => `${path}:${i + 1}`),
    );
    expect(offenders).toEqual([]);
  });
});
