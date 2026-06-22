import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { useBackgroundTasks } from "@/stores/background-tasks-store";
import { RunCard } from "@/components/knowledge/RunCard";

const runsEventsMock = vi.fn().mockResolvedValue([]);
const logsRunsMock = vi.fn().mockResolvedValue([]);

vi.mock("@/lib/api", () => ({
  api: {
    runs: { events: (...a: unknown[]) => runsEventsMock(...a), cancel: vi.fn(), retry: vi.fn() },
    logs: { runs: (...a: unknown[]) => logsRunsMock(...a) },
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  useBackgroundTasks.setState({ tasks: {}, pinnedRunningIds: new Set() });
});

describe("RunCard", () => {
  it("renders running progress", () => {
    useBackgroundTasks.setState({
      tasks: {
        r: {
          runId: "r",
          workflowId: "w",
          kind: "db_index",
          pipeline: "db_index",
          status: "running",
          currentStep: "fetch_samples",
          currentStepDetail: "",
          stepIndex: 2,
          totalSteps: 6,
          progressPct: 33,
          startedAt: 0,
          connectionId: "c",
          extra: {},
          source: "sse",
        },
      },
      pinnedRunningIds: new Set(["r"]),
    });
    render(
      <RunCard
        title="Database"
        kind="db_index"
        projectId="p"
        connectionId="c"
        onTrigger={() => {}}
        triggerLabel="Index database"
      />,
    );
    expect(screen.getByText(/2 of 6/)).toBeTruthy();
  });

  it("renders trigger when idle", () => {
    render(
      <RunCard
        title="Database"
        kind="db_index"
        projectId="p"
        connectionId="c"
        onTrigger={() => {}}
        triggerLabel="Index database"
      />,
    );
    expect(screen.getByRole("button", { name: "Index database" })).toBeTruthy();
  });
});
