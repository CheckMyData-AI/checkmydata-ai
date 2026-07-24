import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const getSummary = vi.fn();
const getUsers = vi.fn();
const listRequests = vi.fn();
const runs = vi.fn();
const errors = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    logs: {
      getSummary: (...a: unknown[]) => getSummary(...a),
      getUsers: (...a: unknown[]) => getUsers(...a),
      listRequests: (...a: unknown[]) => listRequests(...a),
      runs: (...a: unknown[]) => runs(...a),
      errors: (...a: unknown[]) => errors(...a),
      updateError: vi.fn(),
    },
  },
}));

vi.mock("@/stores/app-store", () => {
  const state = {
    activeProject: { id: "p1", name: "Test" },
    setLogsOpen: vi.fn(),
  };
  return {
    useAppStore: Object.assign(
      (sel?: (s: typeof state) => unknown) => (sel ? sel(state) : state),
      { getState: () => state },
    ),
  };
});

import { LogsScreen } from "@/components/logs/LogsScreen";

beforeEach(() => {
  vi.clearAllMocks();
  getSummary.mockRejectedValue(new Error("Failed to load logs"));
  getUsers.mockRejectedValue(new Error("Failed to load logs"));
  listRequests.mockRejectedValue(new Error("Failed to load logs"));
  runs.mockResolvedValue([]);
  errors.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 });
});

describe("LogsScreen load-failure banner (L6)", () => {
  it("stays visible when switching from queries to runs/errors tabs", async () => {
    const user = userEvent.setup({ delay: null });
    render(<LogsScreen />);

    // Banner on the default queries tab.
    expect(await screen.findByText("Failed to load logs")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Retry" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "runs" }));
    expect(screen.getByText("Failed to load logs")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "errors" }));
    expect(screen.getByText("Failed to load logs")).toBeInTheDocument();
  });

  it("Retry re-fetches the queries data", async () => {
    const user = userEvent.setup({ delay: null });
    render(<LogsScreen />);

    const retry = await screen.findByRole("button", { name: "Retry" });
    expect(listRequests).toHaveBeenCalledTimes(1);

    getSummary.mockResolvedValueOnce({
      total_requests: 0,
      successful: 0,
      failed: 0,
      total_llm_calls: 0,
      total_db_queries: 0,
      avg_duration_ms: 0,
      total_tokens: 0,
      total_cost_usd: 0,
      by_status: {},
      by_type: {},
    });
    getUsers.mockResolvedValueOnce([]);
    listRequests.mockResolvedValueOnce({ items: [], total: 0, page: 1, page_size: 50 });

    await user.click(retry);
    await waitFor(() => expect(listRequests).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.queryByText("Failed to load logs")).not.toBeInTheDocument(),
    );
  });
});
