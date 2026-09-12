/**
 * What the header pill says about a set of background tasks (FE-06, half two).
 *
 * The pill counted only `running` and `failed`, so a task created by
 * `insertOptimistic` with `status: "queued"` fell into the final `else` — "1 done" —
 * and the icon chosen beside it was the check. Between clicking "Re-index
 * repository" and the pipeline-status endpoint reporting `is_indexing: true`, the
 * header therefore read "✓ 1 done" for an index that had not started.
 */

export type TaskStatusLike = "queued" | "running" | "completed" | "failed" | string;

export interface TaskSummary {
  label: string;
  icon: "loader" | "check" | "alert";
}

export function summarizeTasks(tasks: { status: TaskStatusLike }[]): TaskSummary {
  const failed = tasks.filter((t) => t.status === "failed").length;
  const running = tasks.filter((t) => t.status === "running").length;
  // Queued is IN FLIGHT, not finished. It was the absence of this branch that made a
  // task one click old read as a completed one.
  const queued = tasks.filter((t) => t.status === "queued").length;
  const done = tasks.length;

  if (running > 0 && failed > 0) {
    return { label: `${running} running, ${failed} failed`, icon: "loader" };
  }
  if (running > 0) {
    return { label: running === 1 ? "1 task" : `${running} tasks`, icon: "loader" };
  }
  if (failed > 0) {
    return { label: failed === 1 ? "1 failed" : `${failed} failed`, icon: "alert" };
  }
  if (queued > 0) {
    return { label: queued === 1 ? "1 queued" : `${queued} queued`, icon: "loader" };
  }
  return { label: done === 1 ? "1 done" : `${done} done`, icon: "check" };
}
