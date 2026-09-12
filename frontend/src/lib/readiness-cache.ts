/**
 * The readiness cache's own staleness (FE-11).
 *
 * `ReadinessCacheEntry` carries `{ ready, checkedAt }`. `checkedAt` was written
 * twice and read nowhere, so once `ready: true` was recorded for a project the gate
 * never re-appeared for the life of the document. Invalidation was entirely
 * event-driven — pipeline completion, the index/sync poll endings — so a change that
 * arrives by no event was never noticed: delete the project's only connection in
 * another tab, and the chat still presents itself as ready to query a source that
 * does not exist, failing at the agent instead of at the gate that exists to
 * prevent exactly that.
 *
 * The TTL does not replace the events; it bounds how long a missed one can lie.
 */

export interface ReadinessCacheEntry {
  ready: boolean;
  checkedAt: number;
}

/** Long enough that the gate is not a nuisance, short enough to notice a change. */
export const READINESS_TTL_MS = 5 * 60 * 1000;

export function isReadinessFresh(
  entry: ReadinessCacheEntry | undefined,
  now: number = Date.now()
): boolean {
  if (!entry) return false;
  return now - entry.checkedAt <= READINESS_TTL_MS;
}
