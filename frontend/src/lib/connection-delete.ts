import { confirmAction } from "@/components/ui/ConfirmModal";

/**
 * One confirmation for deleting a connection, in one place.
 *
 * Two surfaces ask it now — the workspace source card and the shared connection list —
 * and the sentence naming what is destroyed must be the same in both. Two copies is two
 * chances for one of them to go stale and quietly under-report what the click removes,
 * which is the only part of a destructive dialog that matters. "Are you sure" asks a
 * question the user has no way to answer.
 */
export function confirmConnectionDelete(name: string): Promise<boolean> {
  return confirmAction(`Delete connection "${name}"?`, {
    severity: "critical",
    detail:
      "This will permanently remove all DB indexes, sync data, learnings, benchmarks, " +
      "and session notes associated with this connection.",
    confirmText: "DELETE",
  });
}
