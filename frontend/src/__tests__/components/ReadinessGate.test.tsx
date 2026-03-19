import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const readinessMock = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    projects: {
      readiness: (...args: unknown[]) => readinessMock(...args),
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

const onBypass = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
});

function makeReadiness(overrides: Record<string, unknown> = {}) {
  return {
    repo_connected: false,
    repo_indexed: false,
    db_connected: false,
    db_indexed: false,
    code_db_synced: false,
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
});
