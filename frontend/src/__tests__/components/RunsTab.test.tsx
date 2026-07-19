import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { RunsTab } from "@/components/logs/RunsTab";

const RUN = {
  id: "run-1",
  kind: "db_index",
  status: "completed" as const,
  trigger: "manual",
  progress_pct: 100,
  connection_id: "c",
  error: null,
  failure_kind: null,
  started_at: null,
  finished_at: null,
};

const runsMock = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    logs: {
      runs: (...a: unknown[]) => runsMock(...a),
    },
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  runsMock.mockResolvedValue([RUN]);
});

describe("RunsTab", () => {
  it("lists runs on success", async () => {
    render(<RunsTab projectId="p" />);
    await waitFor(() => expect(screen.getByText("db_index")).toBeTruthy());
    expect(screen.getByText("completed")).toBeTruthy();
  });

  it("shows an error state with Retry when the fetch fails (SCN-107)", async () => {
    runsMock.mockRejectedValueOnce(new Error("server down"));
    render(<RunsTab projectId="p" />);
    // Error message surfaces instead of a bare empty state.
    await waitFor(() => expect(screen.getByText("server down")).toBeTruthy());
    expect(screen.queryByText("No runs recorded")).toBeNull();

    // Retry re-fetches and renders the row.
    const retry = screen.getByRole("button", { name: "Retry" });
    runsMock.mockResolvedValueOnce([RUN]);
    fireEvent.click(retry);
    await waitFor(() => expect(screen.getByText("db_index")).toBeTruthy());
  });
});
