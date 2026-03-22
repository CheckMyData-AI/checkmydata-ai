import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mockSchedules = [
  {
    id: "s1",
    title: "Daily report",
    sql_query: "SELECT * FROM orders",
    cron_expression: "0 9 * * *",
    connection_id: "c1",
    is_active: true,
    last_run_at: null,
    alert_conditions: null,
  },
  {
    id: "s2",
    title: "Weekly stats",
    sql_query: "SELECT count(*) FROM users",
    cron_expression: "0 9 * * 1",
    connection_id: "c1",
    is_active: false,
    last_run_at: "2026-03-20T10:00:00Z",
    alert_conditions: null,
  },
];

vi.mock("@/stores/app-store", () => ({
  useAppStore: vi.fn((sel: (s: Record<string, unknown>) => unknown) =>
    sel({
      activeProject: { id: "p1", name: "Test" },
      connections: [{ id: "c1", name: "DB1", db_type: "postgres" }],
      activeConnection: { id: "c1", name: "DB1" },
    }),
  ),
}));

vi.mock("@/components/ui/ConfirmModal", () => ({
  useConfirmStore: vi.fn((sel: (s: Record<string, unknown>) => unknown) =>
    sel({ show: vi.fn().mockResolvedValue(true) }),
  ),
}));

vi.mock("@/lib/api", () => ({
  api: {
    schedules: {
      list: vi.fn().mockResolvedValue(mockSchedules),
      create: vi.fn().mockResolvedValue({ id: "s3", title: "New sched" }),
      update: vi.fn().mockImplementation((_id: string, data: Record<string, unknown>) => ({
        ...mockSchedules[0],
        ...data,
      })),
      delete: vi.fn().mockResolvedValue({}),
      runNow: vi.fn().mockResolvedValue({ status: "success" }),
      history: vi.fn().mockResolvedValue([]),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

vi.mock("@/components/ui/Icon", () => ({
  Icon: (p: { name: string; className?: string }) => (
    <span data-testid={`icon-${p.name}`} className={p.className} />
  ),
}));

const { ScheduleManager } = await import("@/components/schedules/ScheduleManager");

describe("ScheduleManager", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads and displays schedule titles", async () => {
    render(<ScheduleManager />);
    await waitFor(() => {
      expect(screen.getByText("Daily report")).toBeTruthy();
      expect(screen.getByText("Weekly stats")).toBeTruthy();
    });
  });

  it("shows human-readable cron labels", async () => {
    render(<ScheduleManager />);
    await waitFor(() => {
      expect(screen.getByText(/Every day at 9 AM/)).toBeTruthy();
    });
  });

  it("shows New Schedule button", async () => {
    render(<ScheduleManager />);
    await waitFor(() => {
      expect(screen.getByText("New Schedule")).toBeTruthy();
    });
  });

  it("clicking New Schedule shows form", async () => {
    render(<ScheduleManager />);
    await waitFor(() => screen.getByText("New Schedule"));
    await userEvent.click(screen.getByText("New Schedule"));
    expect(screen.getByPlaceholderText("Schedule title")).toBeTruthy();
    expect(screen.getByPlaceholderText("SQL query")).toBeTruthy();
  });

  it("shows Cancel button in form", async () => {
    render(<ScheduleManager />);
    await waitFor(() => screen.getByText("New Schedule"));
    await userEvent.click(screen.getByText("New Schedule"));
    expect(screen.getByText("Cancel")).toBeTruthy();
  });

  it("Create button disabled when form empty", async () => {
    render(<ScheduleManager />);
    await waitFor(() => screen.getByText("New Schedule"));
    await userEvent.click(screen.getByText("New Schedule"));
    const createBtn = screen.getByText("Create");
    expect(createBtn).toHaveProperty("disabled", true);
  });

  it("shows preset/custom cron toggle", async () => {
    render(<ScheduleManager />);
    await waitFor(() => screen.getByText("New Schedule"));
    await userEvent.click(screen.getByText("New Schedule"));
    expect(screen.getByText("Preset")).toBeTruthy();
    expect(screen.getByText("Custom")).toBeTruthy();
  });

  it("shows Alert Conditions section", async () => {
    render(<ScheduleManager />);
    await waitFor(() => screen.getByText("New Schedule"));
    await userEvent.click(screen.getByText("New Schedule"));
    expect(screen.getByText("Alert Conditions")).toBeTruthy();
    expect(screen.getByText("+ Add")).toBeTruthy();
  });

  it("renders status dots for schedules", async () => {
    const { container } = render(<ScheduleManager />);
    await waitFor(() => screen.getByText("Daily report"));
    const dots = container.querySelectorAll(".w-1\\.5.h-1\\.5.rounded-full");
    expect(dots.length).toBeGreaterThanOrEqual(2);
  });
});
