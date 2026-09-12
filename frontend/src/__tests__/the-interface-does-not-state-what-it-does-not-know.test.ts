/**
 * P3 row 24, the frontend half: FE-04, FE-06, FE-07, FE-09, FE-10, FE-11.
 *
 * One shape runs through four of the six. A fetch fails, the catch clears the data
 * and raises a toast, and the render reaches the branch written for "there is
 * nothing here" — so a failure is published as a positive claim about the user's
 * account: the dashboard does not exist, you have saved no queries. The toast that
 * carried the real reason auto-dismisses after ten seconds and the false sentence
 * stays on screen indefinitely.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

describe("a dashboard that failed to load does not claim it was deleted (FE-04)", () => {
  it("separates a 404 from every other failure", async () => {
    const { classifyLoadFailure } = await import("@/lib/load-failure");

    expect(classifyLoadFailure(Object.assign(new Error("Not found"), { status: 404 }))).toBe(
      "missing"
    );
    for (const status of [0, 408, 429, 500, 502, 503, 504]) {
      expect(
        classifyLoadFailure(Object.assign(new Error("boom"), { status })),
        `status ${status} must not read as "it does not exist"`
      ).toBe("unavailable");
    }
    // A TypeError from fetch with no status at all — the offline case.
    expect(classifyLoadFailure(new TypeError("Failed to fetch"))).toBe("unavailable");
  });

  it("an unavailable resource keeps its reason instead of the toast keeping it", async () => {
    const { classifyLoadFailure, describeLoadFailure } = await import("@/lib/load-failure");
    const err = Object.assign(new Error("Upstream timed out"), { status: 504 });
    expect(describeLoadFailure(classifyLoadFailure(err), err)).toContain("Upstream timed out");
  });
});

describe("a saved-queries panel that failed to load says so (FE-07)", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("distinguishes a failed load from an empty list", async () => {
    vi.doMock("@/lib/api", () => ({
      api: { notes: { list: vi.fn().mockRejectedValue(new Error("500")) } },
    }));
    vi.doMock("@/stores/toast-store", () => ({ toast: vi.fn() }));

    const { useNotesStore } = await import("@/stores/notes-store");
    await useNotesStore.getState().loadNotes("p1");

    const state = useNotesStore.getState();
    expect(state.notes).toEqual([]);
    expect(
      state.loadError,
      'without this the drawer renders "No saved queries yet" over 40 saved queries ' +
        "that still exist (FE-07)"
    ).toBeTruthy();
  });

  it("a successful load clears a previous error", async () => {
    vi.doMock("@/lib/api", () => ({
      api: { notes: { list: vi.fn().mockResolvedValue([{ id: "n1" }]) } },
    }));
    vi.doMock("@/stores/toast-store", () => ({ toast: vi.fn() }));

    const { useNotesStore } = await import("@/stores/notes-store");
    useNotesStore.setState({ loadError: "stale failure" });
    await useNotesStore.getState().loadNotes("p1");
    expect(useNotesStore.getState().loadError).toBeNull();
  });
});

describe("a background task that disappears stops spinning (FE-06)", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("a running task absent from the authoritative list is reconciled terminal", async () => {
    const { useBackgroundTasks } = await import("@/stores/background-tasks-store");
    const store = useBackgroundTasks;
    store.setState({
      tasks: {
        "wf-gone": {
          runId: "wf-gone",
          workflowId: "wf-gone",
          pipeline: "index_repo",
          kind: "index_repo",
          status: "running",
          currentStep: "",
          currentStepDetail: "",
          stepIndex: 0,
          totalSteps: 0,
          progressPct: 0,
          connectionId: null,
          // Well past the grace window: this run has been gone long enough that its
          // absence from the authoritative list is information.
          startedAt: Date.now() / 1000 - 600,
          extra: {},
          source: "poll",
        },
      },
    });

    store.getState().reconcileFromActive([]);

    const task = store.getState().tasks["wf-gone"];
    expect(
      task === undefined || task.status !== "running",
      "the SSE pipeline_end was the ONLY transition to terminal, so a reconnect " +
        "landing after the run finished left the pill spinning with a Cancel " +
        "button for a run that had ended — only a reload cleared it (FE-06)"
    ).toBe(true);
  });

  it("a task queued a moment ago is not counted as done", async () => {
    const { summarizeTasks } = await import("@/lib/task-summary");
    const queued = summarizeTasks([
      { status: "queued" },
      { status: "queued" },
    ]);
    expect(queued.label).not.toMatch(/done/i);
    expect(queued.icon).not.toBe("check");

    const done = summarizeTasks([{ status: "completed" }]);
    expect(done.label).toMatch(/done/i);
    expect(done.icon).toBe("check");

    const running = summarizeTasks([{ status: "running" }]);
    expect(running.icon).toBe("loader");
  });
});

describe("the chat does not fight the reader while it streams (FE-09)", () => {
  it("streaming scrolls instantly; reduced motion never animates", async () => {
    const { scrollBehaviorFor } = await import("@/lib/scroll-behavior");
    expect(scrollBehaviorFor({ streaming: true, reducedMotion: false })).toBe("auto");
    expect(scrollBehaviorFor({ streaming: false, reducedMotion: true })).toBe("auto");
    expect(scrollBehaviorFor({ streaming: false, reducedMotion: false })).toBe("smooth");
  });

  it("a reader who scrolled up is left where they are", async () => {
    const { shouldFollowOutput } = await import("@/lib/scroll-behavior");
    expect(shouldFollowOutput({ scrollTop: 900, scrollHeight: 1000, clientHeight: 100 })).toBe(
      true
    );
    expect(
      shouldFollowOutput({ scrollTop: 100, scrollHeight: 5000, clientHeight: 400 }),
      "every token yanked the viewport back to the bottom, so re-reading the " +
        "previous answer's SQL was impossible until the stream finished (FE-09)"
    ).toBe(false);
  });
});

describe("the readiness cache goes stale on its own (FE-11)", () => {
  it("checkedAt is read, not merely written", async () => {
    const { isReadinessFresh, READINESS_TTL_MS } = await import("@/lib/readiness-cache");
    const now = Date.now();
    expect(isReadinessFresh({ ready: true, checkedAt: now }, now)).toBe(true);
    expect(
      isReadinessFresh({ ready: true, checkedAt: now - READINESS_TTL_MS - 1 }, now),
      "invalidation was entirely event-driven, so a connection deleted in another " +
        "tab was never noticed and the chat presented itself as ready to query a " +
        "source that no longer existed (FE-11)"
    ).toBe(false);
    expect(isReadinessFresh(undefined, now)).toBe(false);
  });
});
