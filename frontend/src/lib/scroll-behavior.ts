/**
 * When the chat may move the viewport, and how (FE-09).
 *
 * The scroll effect listed `streamingText` among its dependencies and `handleToken`
 * appends every SSE chunk to it, so each token committed a render and fired a fresh
 * `scrollIntoView({ behavior: "smooth" })`. Unconditional — no check of whether the
 * reader was already at the bottom — and the behaviour was named in JavaScript,
 * where the `prefers-reduced-motion` block in `globals.css` cannot reach it: that
 * block zeroes the `--dur-*` custom properties, and there is no `scroll-behavior`
 * declaration anywhere in the file to override.
 */

/** Within this many pixels of the bottom counts as "following the output". */
export const FOLLOW_THRESHOLD_PX = 120;

export function scrollBehaviorFor(opts: {
  streaming: boolean;
  reducedMotion: boolean;
}): ScrollBehavior {
  // A smooth scroll per token is an animation that never finishes before the next
  // one starts; and a reader who asked the OS for less motion asked for this too.
  return opts.streaming || opts.reducedMotion ? "auto" : "smooth";
}

export function shouldFollowOutput(box: {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
}): boolean {
  const distanceFromBottom = box.scrollHeight - box.scrollTop - box.clientHeight;
  return distanceFromBottom <= FOLLOW_THRESHOLD_PX;
}
