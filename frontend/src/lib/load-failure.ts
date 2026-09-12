/**
 * Telling "this does not exist" apart from "I could not reach the server" (FE-04).
 *
 * `loadDashboard` caught every error into a toast and left `dashboard` at `null`,
 * so the render reached the `!dashboard` branch — whose only content is the sentence
 * "Dashboard not found" and a link back to the app. A network failure, a 500, a 504
 * and a genuine 404 all produced the same permanent screen, and the toast carrying
 * the real reason dismisses itself after ten seconds, leaving a false statement up
 * indefinitely with no Retry on it.
 *
 * A missing resource is a fact about the account; everything else is a fact about
 * this moment. They are different sentences and different affordances, so they are
 * different states.
 */

export type LoadFailure = "missing" | "unavailable";

/** 404 alone means the thing is gone. Anything else — including no status — does not. */
export function classifyLoadFailure(error: unknown): LoadFailure {
  const status = (error as { status?: number } | null)?.status;
  return status === 404 ? "missing" : "unavailable";
}

export function describeLoadFailure(kind: LoadFailure, error: unknown): string {
  if (kind === "missing") {
    return "This dashboard no longer exists, or was never shared with you.";
  }
  const detail = error instanceof Error ? error.message : "";
  return detail
    ? `Could not load this dashboard: ${detail}`
    : "Could not load this dashboard. The server did not respond.";
}
