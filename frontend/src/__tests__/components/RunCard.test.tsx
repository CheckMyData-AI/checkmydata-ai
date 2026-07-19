import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { useBackgroundTasks } from "@/stores/background-tasks-store";
import { RunCard } from "@/components/knowledge/RunCard";

const runsEventsMock = vi.fn().mockResolvedValue([]);
const logsRunsMock = vi.fn().mockResolvedValue([]);
const cancelMock = vi.fn().mockResolvedValue({});
const retryMock = vi.fn().mockResolvedValue({});
const toastMock = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    runs: {
      events: (...a: unknown[]) => runsEventsMock(...a),
      cancel: (...a: unknown[]) => cancelMock(...a),
      retry: (...a: unknown[]) => retryMock(...a),
    },
    logs: { runs: (...a: unknown[]) => logsRunsMock(...a) },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: (...a: unknown[]) => toastMock(...a),
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

  it("toasts when cancelling a running run fails (SCN-062)", async () => {
    cancelMock.mockRejectedValueOnce(new Error("network"));
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
    fireEvent.click(screen.getByRole("button", { name: "Cancel Database" }));
    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith("Failed to cancel run", "error"),
    );
  });

  it("toasts when retrying a failed run fails (SCN-062)", async () => {
    retryMock.mockRejectedValueOnce(new Error("network"));
    useBackgroundTasks.setState({
      tasks: {
        r: {
          runId: "r",
          workflowId: "w",
          kind: "db_index",
          pipeline: "db_index",
          status: "failed",
          currentStep: "",
          currentStepDetail: "",
          stepIndex: 0,
          totalSteps: 6,
          progressPct: 0,
          startedAt: 0,
          connectionId: "c",
          extra: {},
          source: "sse",
          error: "boom",
        },
      },
      pinnedRunningIds: new Set(),
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
    fireEvent.click(screen.getByRole("button", { name: "Retry Database" }));
    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith("Failed to retry run", "error"),
    );
  });
});
