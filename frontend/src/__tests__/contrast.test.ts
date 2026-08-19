import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Contrast, computed from the token layer rather than asserted about it.
 *
 * The 2026-08-16 UX audit recorded "contrast is stated, not measured in situ" as
 * something it could not verify. Measuring it found a real defect on the
 * element this design is remembered by: the seal painted its WORD in the state's
 * colour, which put `Unverified` at 2.13:1 on the light panel — under even the
 * 3:1 floor for a mark, let alone the 4.5:1 for text. The pack says the word
 * goes in `--ink` and the colour rides the glyph; the component's own comment
 * said so too, while the code did the opposite.
 *
 * This file exists so that stops being a thing a human has to notice.
 */

const CSS = readFileSync(resolve(__dirname, "../app/globals.css"), "utf8");

// ── colour maths, in the sRGB space the browser composites in ───────────────
type RGB = [number, number, number];

function hexToRgb(hex: string): RGB {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255) as RGB;
}

/** oklch() → sRGB, enough of it for the two amber tokens the pack derives. */
function oklchToRgb(l: number, c: number, hDeg: number): RGB {
  const h = (hDeg * Math.PI) / 180;
  const a = c * Math.cos(h);
  const b = c * Math.sin(h);
  const l_ = l + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = l - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = l - 0.0894841775 * a - 1.291485548 * b;
  const [L, M, S] = [l_ ** 3, m_ ** 3, s_ ** 3];
  const lin = [
    +4.0767416621 * L - 3.3077115913 * M + 0.2309699292 * S,
    -1.2684380046 * L + 2.6097574011 * M - 0.3413193965 * S,
    -0.0041960863 * L - 0.7034186147 * M + 1.707614701 * S,
  ];
  return lin.map((v) => {
    const clamped = Math.max(0, Math.min(1, v));
    return clamped <= 0.0031308 ? clamped * 12.92 : 1.055 * clamped ** (1 / 2.4) - 0.055;
  }) as RGB;
}

function parse(value: string): RGB {
  const hex = value.match(/^#[0-9a-fA-F]{3,8}$/);
  if (hex) return hexToRgb(value);
  const oklch = value.match(/^oklch\(\s*([\d.]+)%\s+([\d.]+)\s+([\d.]+)\s*\)$/);
  if (oklch) return oklchToRgb(Number(oklch[1]) / 100, Number(oklch[2]), Number(oklch[3]));
  throw new Error(`contrast test cannot parse ${value}`);
}

/** Alpha compositing happens in gamma space, which is where CSS does it. */
function over(fg: RGB, alpha: number, bg: RGB): RGB {
  return fg.map((c, i) => c * alpha + bg[i] * (1 - alpha)) as RGB;
}

function luminance([r, g, b]: RGB): number {
  const lin = [r, g, b].map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}

function ratio(a: RGB, b: RGB): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

/**
 * Read a token out of the shipped stylesheet, per theme.
 *
 * Anchored on the PACK's own block header rather than on the first `:root {` in
 * the file — globals.css has four `:root` blocks (the pack, the compatibility
 * layer, and two the marketing layer owns) and the naive slice read the wrong
 * one, reporting tokens as missing that are plainly there.
 */
const PACK = CSS.indexOf("SHELEG Design — Ledger token layer (light");
function token(name: string, theme: "light" | "dark"): RGB {
  const darkAt = CSS.indexOf('[data-theme="dark"] {', PACK);
  const block =
    theme === "light"
      ? CSS.slice(PACK, darkAt)
      : CSS.slice(darkAt, CSS.indexOf("Compatibility layer"));
  const find = (source: string) => [
    ...source.matchAll(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{3,8}|oklch\\([^)]*\\));`, "g")),
  ];
  let matches = find(block);
  // A token the dark twin does not override keeps its light value — `--ok` and
  // `--danger` are the same hex in both themes and are declared once. Modelling
  // the cascade rather than demanding a redeclaration is the difference between
  // reading the stylesheet and asserting about it.
  if (matches.length === 0 && theme === "dark") matches = find(CSS.slice(PACK, darkAt));
  if (matches.length === 0) throw new Error(`${name} not found in the ${theme} block`);
  return parse(matches[matches.length - 1][1].trim());
}

const THEMES = ["light", "dark"] as const;

describe("contrast, measured on the surfaces this app actually composes", () => {
  it.each(THEMES)("keeps a status WORD readable in %s — it is never the coloured part", (theme) => {
    // The seal and the badges put their word in --ink over a 10-12% tint. That
    // is the pack's rule, and it is the reason those surfaces measure 16-18:1
    // where the coloured-word version measured 2.13.
    const ink = token("--ink", theme);
    const panel = token("--panel", theme);
    for (const [name, alpha] of [["--ok", 0.1], ["--warn", 0.12], ["--danger", 0.1], ["--info", 0.1]] as const) {
      const tint = over(token(name, theme), alpha, panel);
      expect(ratio(ink, tint), `${name} chip in ${theme}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it.each(THEMES)("keeps secondary prose above AA in %s", (theme) => {
    const alpha = theme === "light" ? 0.72 : 0.7;
    const panel = token("--panel", theme);
    const inkTwo = over(token("--ink", theme), alpha, panel);
    expect(ratio(inkTwo, panel)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(THEMES)("holds --muted to the floor it is documented at in %s", (theme) => {
    // NOT 4.5. `--muted` is the pack's measured value and composites to 4.13:1
    // in light — under AA by 0.37, documented in DESIGN_SYSTEM.md §1.2, and
    // reserved for column heads and axis ticks where position repeats the word.
    // The floor here is the non-text floor, and the test says which one it is so
    // that a later drift downward still fails.
    const alpha = theme === "light" ? 0.55 : 0.5;
    const panel = token("--panel", theme);
    const muted = over(token("--ink", theme), alpha, panel);
    expect(ratio(muted, panel)).toBeGreaterThanOrEqual(3.0);
    if (theme === "light") expect(ratio(muted, panel)).toBeGreaterThan(4.0);
  });

  it("keeps the accent readable as text on the field, in both themes", () => {
    for (const theme of THEMES) {
      expect(ratio(token("--accent", theme), token("--bg", theme))).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("keeps the ink button's own label at AAA on both themes", () => {
    for (const theme of THEMES) {
      expect(ratio(token("--on-ink", theme), token("--ink", theme))).toBeGreaterThanOrEqual(7);
    }
  });
});
