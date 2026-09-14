/**
 * A failure message names the outcome; the step log names the place.
 *
 * `GET /api/runs/{id}/events` returns each step with its status, detail, `elapsed_ms`
 * and `progress_pct`, and its typed client (`runs.ts:24-25`) had no caller. So when a
 * repository index died at `graph_build`, the interface could say "stale run reaped"
 * and nothing about which step, how far in, or how long it had been working.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const events = vi.fn();
vi.mock("@/lib/api", () => ({ api: { runs: { events } } }));

const ev = (over = {}) => ({
  ts: "2026-09-14T10:00:00Z",
  step: "graph_build",
  status: "started",
  detail: "",
  elapsed_ms: null,
  progress_pct: null,
  level: "info",
  ...over,
});

beforeEach(() => vi.clearAllMocks());

describe("RunStepTimeline", () => {
  it("names the step, its detail and how long it took", async () => {
    events.mockResolvedValueOnce([
      ev({ step: "clone_or_pull", status: "completed", elapsed_ms: 1500, detail: "82 files" }),
      ev({ step: "graph_build", status: "failed", level: "error", detail: "stale run reaped" }),
    ]);
    const { RunStepTimeline } = await import("@/components/knowledge/RunStepTimeline");
    render(<RunStepTimeline runId="r1" />);

    await waitFor(() => expect(screen.getByText("clone_or_pull")).toBeTruthy());
    expect(screen.getByText(/82 files/)).toBeTruthy();
    expect(screen.getByText("1.5s")).toBeTruthy();
    expect(screen.getByText("graph_build")).toBeTruthy();
    expect(screen.getByText(/stale run reaped/)).toBeTruthy();
  });

  it("shows sub-second steps in milliseconds rather than as 0.0s", async () => {
    events.mockResolvedValueOnce([ev({ status: "completed", elapsed_ms: 120 })]);
    const { RunStepTimeline } = await import("@/components/knowledge/RunStepTimeline");
    render(<RunStepTimeline runId="r1" />);
    await waitFor(() => expect(screen.getByText("120ms")).toBeTruthy());
  });

  it("says a run recorded nothing rather than rendering an empty list", async () => {
    events.mockResolvedValueOnce([]);
    const { RunStepTimeline } = await import("@/components/knowledge/RunStepTimeline");
    render(<RunStepTimeline runId="r1" />);
    await waitFor(() =>
      expect(screen.getByText(/ended before the first one started/i)).toBeTruthy(),
    );
  });

  it("offers a retry when the log cannot be loaded", async () => {
    events.mockRejectedValueOnce(new Error("run not found"));
    const { RunStepTimeline } = await import("@/components/knowledge/RunStepTimeline");
    render(<RunStepTimeline runId="r1" />);
    await waitFor(() => expect(screen.getByText("run not found")).toBeTruthy());

    events.mockResolvedValueOnce([ev({ status: "completed" })]);
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() => expect(screen.getByText("graph_build")).toBeTruthy());
  });
});
