import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const readinessMock = vi.fn();
const pipelineStatusMock = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    projects: {
      readiness: (...args: unknown[]) => readinessMock(...args),
      pipelineStatus: (...args: unknown[]) => pipelineStatusMock(...args),
    },
    repos: { index: vi.fn().mockResolvedValue({ workflow_id: "w1" }) },
    connections: {
      indexDb: vi.fn().mockResolvedValue({}),
      triggerSync: vi.fn().mockResolvedValue({}),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

// Short polls so a watched step can finish inside a test.
vi.mock("@/lib/polling", () => ({ POLL_INTERVAL_MS: 10, MAX_POLL_MS: 60_000 }));

const onBypass = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  pipelineStatusMock.mockRejectedValue(new Error("pipeline status unavailable"));
});

function makeReadiness(overrides: Record<string, unknown> = {}) {
  return {
    repo_connected: false,
    repo_indexed: false,
    db_connected: false,
    db_indexed: false,
    code_db_synced: false,
    db_indexing: false,
    code_db_syncing: false,
    ready: false,
    missing_steps: [],
    active_connection_id: null,
    last_indexed_at: null,
    commits_behind: 0,
    is_stale: false,
    ...overrides,
  };
}

async function renderReadinessGate(
  readiness: Record<string, unknown> = {},
) {
  readinessMock.mockResolvedValue(makeReadiness(readiness));
  const { ReadinessGate } = await import(
    "@/components/chat/ReadinessGate"
  );
  return render(
    <ReadinessGate projectId="p1" connectionId={null} onBypass={onBypass} />,
  );
}

describe("ReadinessGate", () => {
  it("shows status dashboard items", async () => {
    await renderReadinessGate();
    await waitFor(() => {
      expect(screen.getByText(/Git repository/)).toBeInTheDocument();
      expect(screen.getByText(/Database connection/)).toBeInTheDocument();
    });
  });

  it("has Chat anyway bypass button when not ready", async () => {
    await renderReadinessGate();
    await waitFor(() => {
      expect(screen.getByText("Chat anyway")).toBeInTheDocument();
    });
  });

  it("clicking Chat anyway calls onBypass", async () => {
    await renderReadinessGate();
    await waitFor(() => expect(screen.getByText("Chat anyway")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Chat anyway"));
    expect(onBypass).toHaveBeenCalled();
  });

  it("shows warning about less accurate queries when not fully set up", async () => {
    await renderReadinessGate();
    await waitFor(() => {
      expect(
        screen.getByText(/SQL queries may be less accurate/),
      ).toBeInTheDocument();
    });
  });

  it("calls onBypass when all steps are ready and not stale", async () => {
    readinessMock.mockResolvedValue(makeReadiness({
      repo_connected: true,
      repo_indexed: true,
      db_connected: true,
      db_indexed: true,
      code_db_synced: true,
      ready: true,
      active_connection_id: "c1",
    }));
    const { ReadinessGate } = await import("@/components/chat/ReadinessGate");
    render(
      <ReadinessGate projectId="p1" connectionId="c1" onBypass={onBypass} />,
    );
    await waitFor(() => {
      expect(onBypass).toHaveBeenCalled();
    });
  });

  it("shows green Done indicators for completed steps", async () => {
    await renderReadinessGate({
      repo_connected: true,
      repo_indexed: true,
      db_connected: false,
    });
    await waitFor(() => {
      const doneLabels = screen.getAllByText("Done");
      expect(doneLabels.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("shows staleness warning when is_stale is true", async () => {
    readinessMock.mockResolvedValue(makeReadiness({
      repo_connected: true,
      repo_indexed: true,
      db_connected: true,
      db_indexed: true,
      code_db_synced: true,
      ready: true,
      active_connection_id: "c1",
      last_indexed_at: new Date(Date.now() - 8 * 24 * 60 * 60 * 1000).toISOString(),
      commits_behind: 5,
      is_stale: true,
    }));
    const { ReadinessGate } = await import("@/components/chat/ReadinessGate");
    render(
      <ReadinessGate projectId="p1" connectionId="c1" onBypass={onBypass} />,
    );
    await waitFor(() => {
      expect(screen.getByText(/Re-indexing recommended/)).toBeInTheDocument();
      expect(screen.getByText("Re-index")).toBeInTheDocument();
    });
  });

  it("shows last indexed time when available", async () => {
    await renderReadinessGate({
      repo_connected: true,
      repo_indexed: true,
      last_indexed_at: new Date(Date.now() - 3600_000).toISOString(),
    });
    await waitFor(() => {
      expect(screen.getByText(/Last indexed/)).toBeInTheDocument();
    });
  });

  // Reported from production on 2026-09-15: the rail showed "Database indexed — Run" and
  // "Code ↔ DB synced — Run" while an index was mid-flight, and the sync summary said
  // `completed`. Two defects, one screen.
  describe("a step already running", () => {
    it("is shown as running rather than offered as an action", async () => {
      readinessMock.mockResolvedValue(makeReadiness({
        repo_connected: true,
        repo_indexed: true,
        db_connected: true,
        db_indexing: true,
        active_connection_id: "c1",
      }));
      const { ReadinessGate } = await import("@/components/chat/ReadinessGate");
      render(
        <ReadinessGate projectId="p1" connectionId="c1" onBypass={onBypass} />,
      );
      await waitFor(() => {
        expect(screen.getByText("Running…")).toBeInTheDocument();
      });
      // …and the button that would start a second one is not offered. The second run is
      // refused by the partial unique index, so the click would appear to do nothing.
      // Every remaining "Run" belongs to another step: with `db_indexing` set, the
      // database row must not have one.
      // Only the sync step may offer one. Without the fix there are two, and the second
      // starts a run the partial unique index refuses.
      expect(screen.queryAllByRole("button", { name: "Run" })).toHaveLength(1);
    });

    // B-27 D3: a repository index in flight was offered "Run", and the click answered
    // 409 "Indexing already in progress".
    it("a repository index in flight is shown running, not offered", async () => {
      readinessMock.mockResolvedValue(makeReadiness({
        repo_connected: true,
        repo_indexed: false,
        repo_indexing: true,
        db_connected: true,
        db_indexed: true,
        code_db_synced: true,
        active_connection_id: "c1",
      }));
      const { ReadinessGate } = await import("@/components/chat/ReadinessGate");
      render(
        <ReadinessGate projectId="p1" connectionId="c1" onBypass={onBypass} />,
      );
      await waitFor(() => {
        expect(screen.getByText("Running…")).toBeInTheDocument();
      });
      expect(screen.queryAllByRole("button", { name: "Run" })).toHaveLength(0);
    });

    it("does not hide a step that finished while another one runs", async () => {
      // The sync summary read `completed` at 20:52 and the rail said "Run", because
      // `is_synced` was consulted only inside `if indexed:` and an index had started at
      // 21:34. One step's progress is not another step's state.
      readinessMock.mockResolvedValue(makeReadiness({
        repo_connected: true,
        repo_indexed: true,
        db_connected: true,
        db_indexing: true,
        code_db_synced: true,
        active_connection_id: "c1",
      }));
      const { ReadinessGate } = await import("@/components/chat/ReadinessGate");
      render(
        <ReadinessGate projectId="p1" connectionId="c1" onBypass={onBypass} />,
      );
      await waitFor(() => {
        expect(screen.getAllByText("Done").length).toBeGreaterThanOrEqual(4);
      });
    });
  });

  // T04b/F-W3 (audit 2026-09-23 §3.3): polling started only from a click, so a step that
  // was already running when the gate mounted stayed "Running…" until a remount.
  it("notices a step that was already running finish", async () => {
    const busy = makeReadiness({
      repo_connected: true,
      repo_indexed: true,
      db_connected: true,
      db_indexing: true,
      active_connection_id: "c1",
    });
    readinessMock.mockResolvedValueOnce(busy).mockResolvedValueOnce(busy).mockResolvedValue(
      makeReadiness({ ...busy, db_indexing: false, db_indexed: true }),
    );
    const { ReadinessGate } = await import("@/components/chat/ReadinessGate");
    render(<ReadinessGate projectId="p1" connectionId="c1" onBypass={onBypass} />);

    expect(await screen.findByText("Running…")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Running…")).toBeNull(), { timeout: 3000 });
    expect(readinessMock.mock.calls.length).toBeGreaterThanOrEqual(3);
  });

  // B-27 (SCN-045): with the pipeline endpoint failing, a step that FINISHED ended as
  // "timed out" — the failure was read as "still busy" until the ceiling.
  it("a step that finished completes even when the pipeline status call fails", async () => {
    const { toast } = await import("@/stores/toast-store");
    const before = makeReadiness({
      repo_connected: true,
      repo_indexed: true,
      db_connected: true,
      active_connection_id: "c1",
    });
    readinessMock
      .mockResolvedValueOnce(before)
      .mockResolvedValue(makeReadiness({ ...before, db_indexed: true }));
    const { ReadinessGate } = await import("@/components/chat/ReadinessGate");
    render(<ReadinessGate projectId="p1" connectionId="c1" onBypass={onBypass} />);
    const runs = await screen.findAllByRole("button", { name: "Run" });
    await userEvent.click(runs[0]);
    await waitFor(
      () => expect(toast).toHaveBeenCalledWith(expect.stringMatching(/completed$/), "success"),
      { timeout: 3000 },
    );
    expect(toast).not.toHaveBeenCalledWith(expect.stringMatching(/timed out/), "error");
  });
});
