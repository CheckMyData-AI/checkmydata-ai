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

async function renderReadinessGate(
  readiness: Record<string, unknown> = {},
) {
  const base = {
    repo_connected: false,
    repo_indexed: false,
    db_connected: false,
    db_indexed: false,
    code_db_synced: false,
    ready: false,
    missing_steps: [],
    active_connection_id: null,
    ...readiness,
  };
  readinessMock.mockResolvedValue(base);
  const { ReadinessGate } = await import(
    "@/components/chat/ReadinessGate"
  );
  return render(
    <ReadinessGate projectId="p1" connectionId={null} onBypass={onBypass} />,
  );
}

describe("ReadinessGate", () => {
  it("shows setup checklist items", async () => {
    await renderReadinessGate();
    await waitFor(() => {
      expect(screen.getByText(/Connect a Git repository/)).toBeInTheDocument();
      expect(screen.getByText(/Add a database connection/)).toBeInTheDocument();
    });
  });

  it("has Chat anyway bypass button", async () => {
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

  it("shows warning about less accurate queries", async () => {
    await renderReadinessGate();
    await waitFor(() => {
      expect(
        screen.getByText(/SQL queries may be less accurate/),
      ).toBeInTheDocument();
    });
  });

  it("returns null when all steps are ready", async () => {
    readinessMock.mockResolvedValue({
      repo_connected: true,
      repo_indexed: true,
      db_connected: true,
      db_indexed: true,
      code_db_synced: true,
      ready: true,
      missing_steps: [],
      active_connection_id: "c1",
    });
    const { ReadinessGate } = await import("@/components/chat/ReadinessGate");
    const { container } = render(
      <ReadinessGate projectId="p1" connectionId="c1" onBypass={onBypass} />,
    );
    await waitFor(() => {
      expect(container.innerHTML).toBe("");
    });
  });
});
