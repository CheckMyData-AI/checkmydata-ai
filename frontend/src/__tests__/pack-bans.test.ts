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

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) {
      if (entry === "__tests__" || entry === "node_modules") continue;
      sourceFiles(p, out);
    } else if (entry.endsWith(".tsx") || entry.endsWith(".ts")) {
      // `.ts` as well as `.tsx`: the chart adapter is a plain module and it is
      // exactly where a series colour would be hardcoded.
      out.push(p);
    }
  }
  return out;
}

const FILES = sourceFiles(SRC).map((p) => ({ path: relative(SRC, p), lines: readFileSync(p, "utf8").split("\n") }));

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

  it("paints no chart with a colour literal — a series follows the theme or it lies", () => {
    // Recharts takes its colours as props, so a hex here is invisible to a
    // rendering test (jsdom draws no series marks) and invisible to the token
    // layer. The eight rgba() literals this replaced were the retired palette
    // and painted the same chart in light and dark.
    const viz = FILES.filter((f) => f.path.startsWith("components/viz/"));
    expect(viz.length).toBeGreaterThan(2);
    const offenders = viz.flatMap(({ path, lines }) =>
      lines
        .map((line, i) => ({ line, i }))
        // ANY colour literal, not only one assigned to `fill`/`stroke`: a
        // planted `const base = "#3b82f6"` in the ramp itself slipped past the
        // narrower pattern, and the ramp is the one place that matters most.
        .filter(({ line }) => !line.trimStart().startsWith("//") && !line.trimStart().startsWith("*"))
        .filter(({ line }) => /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/.test(line))
        .map(({ i }) => `${path}:${i + 1}`),
    );
    expect(offenders).toEqual([]);
  });

  it("sets no font size outside the pack's ramp", () => {
    // The craft bar's "no ad-hoc font size anywhere in the diff" is only
    // achievable because the ramp ships as tokens. 484 bracket sizes across 78
    // files were swept onto it; 11px and 13px had no step and were rounded to
    // the nearest one that exists rather than given a token the pack does not
    // own.
    const offenders = FILES.flatMap(({ path, lines }) =>
      lines
        .map((line, i) => ({ line, i }))
        .filter(({ line }) => /\btext-\[\d+(px|rem)\]/.test(line))
        .map(({ i }) => `${path}:${i + 1}`),
    );
    expect(offenders).toEqual([]);
  });

  it("paints no surface in raw black or white — a scrim follows the theme too", () => {
    // The defect: `bg-black/50` on the dialog overlay. Over a cream field it
    // reads as another product's modal, and over a near-black one it does
    // nothing at all. A planted revert of it went undetected until this check
    // existed, because nothing else looks at the shadcn layer's surfaces.
    //
    // Deliberately narrow — SURFACES only. `text-white` on `bg-destructive` is
    // shadcn's own default for a variant this project overrides anyway, and the
    // red it sits on is the same hex in both themes, so white is correct there.
    // `[stroke='#ccc']` in chart.tsx is an attribute SELECTOR matching
    // Recharts' defaults in order to override them, not a colour being painted.
    const offenders = FILES.filter((f) => f.path.startsWith("components/")).flatMap(
      ({ path, lines }) =>
        lines
          .map((line, i) => ({ line, i }))
          .filter(({ line }) => /\b(bg-black|bg-white)(\/\d+)?\b/.test(line))
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
        // `(?!-)` matters: `bg-accent-weak` is the pack's OWN selected-row tint
        // and `\b` alone flags it, which is a false positive that would push an
        // author to break the pack in order to satisfy the check.
        .filter(({ line }) => /\b(bg-accent(?!-)|text-accent-foreground|bg-muted(?!-))\b/.test(line))
        .map(({ i }) => `${path}:${i + 1}`),
    );
    expect(offenders).toEqual([]);
  });
});
