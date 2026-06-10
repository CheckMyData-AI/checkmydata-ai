/**
 * Shared motion vocabulary for the whole product.
 *
 * One source of truth consumed by:
 *  - Framer Motion (`motion`) inside /app — springs + tween presets
 *  - GSAP scroll choreography on marketing pages — eases as arrays/strings
 *  - CSS custom properties mirror these in globals.css (`--ease-*`)
 *
 * Durations are seconds (Framer/GSAP convention).
 */

export const DUR = {
  /** Micro feedback: presses, hovers, toggles. */
  fast: 0.16,
  /** UI state changes: list items, chips, tooltips. */
  base: 0.26,
  /** Panel/card entrances, answer reveals. */
  slow: 0.45,
  /** Hero / cinematic beats only. */
  cinematic: 0.8,
} as const;

/** Cubic-bezier curves (match --ease-* tokens in globals.css). */
export const EASE = {
  outQuart: [0.23, 1, 0.32, 1],
  outExpo: [0.16, 1, 0.3, 1],
  inOutStrong: [0.77, 0, 0.175, 1],
  drawer: [0.32, 0.72, 0, 1],
} as const;

/** GSAP string equivalents of EASE. */
export const GSAP_EASE = {
  outQuart: "power4.out",
  outExpo: "expo.out",
  inOutStrong: "power3.inOut",
} as const;

/** Framer Motion spring presets. */
export const SPRING = {
  /** Chat messages entering the timeline — decisive but soft landing. */
  message: { type: "spring" as const, stiffness: 460, damping: 40, mass: 0.9 },
  /** Panels, modals, drawers. */
  panel: { type: "spring" as const, stiffness: 360, damping: 34, mass: 1 },
  /** Small chips, badges, stage dots. */
  chip: { type: "spring" as const, stiffness: 620, damping: 34, mass: 0.7 },
} as const;

/** Stagger interval between sibling items (s). */
export const STAGGER = {
  tight: 0.04,
  base: 0.07,
  loose: 0.12,
} as const;
