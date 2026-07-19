import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { useBackgroundTasks } from "@/stores/background-tasks-store";
import { ActiveTasksWidget } from "@/components/tasks/ActiveTasksWidget";

const cancelMock = vi.fn().mockResolvedValue({ cancelled: true, run_id: "r1" });
const retryMock = vi.fn().mockResolvedValue({});
const toastMock = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    runs: {
      cancel: (...a: unknown[]) => cancelMock(...a),
      retry: (...a: unknown[]) => retryMock(...a),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: (...a: unknown[]) => toastMock(...a),
}));

const RUNNING_TASK = {
  runId: "r1",
  workflowId: "w",
  kind: "db_index",
  pipeline: "db_index",
  status: "running" as const,
  currentStep: "introspect_schema",
  currentStepDetail: "",
  stepIndex: 2,
  totalSteps: 6,
  progressPct: 33,
  startedAt: 0,
  connectionId: "c",
  extra: {},
  source: "sse" as const,
};

beforeEach(() => {
  vi.clearAllMocks();
  useBackgroundTasks.setState({ tasks: {}, pinnedRunningIds: new Set() });
});

describe("ActiveTasksWidget progress + controls", () => {
  it("shows N/M and a cancel control for a running task", () => {
    useBackgroundTasks.setState({
      tasks: {
        r1: {
          runId: "r1",
          workflowId: "w",
          kind: "db_index",
          pipeline: "db_index",
          status: "running",
          currentStep: "introspect_schema",
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
      pinnedRunningIds: new Set(["r1"]),
    });

    render(<ActiveTasksWidget />);
    fireEvent.click(screen.getByRole("button", { name: /Background tasks/i }));
    expect(screen.getByText("2/6")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /cancel run/i }));
    expect(cancelMock).toHaveBeenCalledWith("r1");
  });

  it("toasts when cancelling a task fails (SCN-105)", async () => {
    cancelMock.mockRejectedValueOnce(new Error("network"));
    useBackgroundTasks.setState({
      tasks: { r1: RUNNING_TASK },
      pinnedRunningIds: new Set(["r1"]),
    });

    render(<ActiveTasksWidget />);
    fireEvent.click(screen.getByRole("button", { name: /Background tasks/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancel run/i }));

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith("Failed to cancel task", "error"),
    );
  });

  it("toasts when retrying a failed task fails (SCN-105)", async () => {
    retryMock.mockRejectedValueOnce(new Error("network"));
    useBackgroundTasks.setState({
      tasks: {
        r1: { ...RUNNING_TASK, status: "failed", error: "boom" },
      },
      pinnedRunningIds: new Set(),
    });

    render(<ActiveTasksWidget />);
    fireEvent.click(screen.getByRole("button", { name: /Background tasks/i }));
    fireEvent.click(screen.getByRole("button", { name: /retry run/i }));

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith("Failed to retry task", "error"),
    );
  });
});
