import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Dashboard } from "@/lib/api";

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("@/components/ui/Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

vi.mock("@/components/ui/Tooltip", () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mutable state so individual tests can flip the caller's role (drives usePermission).
const mockState: { activeProject: { id: string } | null; userRole: string | null } = {
  activeProject: { id: "proj-1" },
  userRole: "editor",
};

vi.mock("@/stores/app-store", () => ({
  useAppStore: (selector: (s: typeof mockState) => unknown) => selector(mockState),
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

vi.mock("@/components/ui/ConfirmModal", () => ({
  confirmAction: vi.fn().mockResolvedValue(true),
}));

vi.mock("@/components/dashboards/DashboardBuilder", () => ({
  DashboardBuilder: () => <div data-testid="dashboard-builder">Builder</div>,
}));

vi.mock("@/lib/api", () => ({
  api: {
    dashboards: {
      list: vi.fn(),
      delete: vi.fn(),
    },
  },
}));

const { api } = await import("@/lib/api");
const { toast } = await import("@/stores/toast-store");
const { confirmAction } = await import("@/components/ui/ConfirmModal");

function makeDashboard(overrides: Partial<Dashboard> = {}): Dashboard {
  return {
    id: "dash-1",
    project_id: "proj-1",
    creator_id: "u1",
    title: "My Dashboard",
    layout_json: null,
    cards_json: null,
    is_shared: false,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockState.userRole = "editor";
  vi.mocked(confirmAction).mockResolvedValue(true);
});

async function renderList() {
  const { DashboardList } = await import("@/components/dashboards/DashboardList");
  return render(<DashboardList />);
}

describe("DashboardList", () => {
  it("renders loading then list", async () => {
    let resolveList!: (v: Dashboard[]) => void;
    const listPromise = new Promise<Dashboard[]>((r) => {
      resolveList = r;
    });
    vi.mocked(api.dashboards.list).mockReturnValue(listPromise);

    const { container } = await renderList();

    await waitFor(() => {
      expect(container.querySelector(".animate-spin")).toBeInTheDocument();
    });

    resolveList([makeDashboard({ id: "d1", title: "Alpha" })]);

    await waitFor(() => {
      expect(screen.getByText("Alpha")).toBeInTheDocument();
    });
    expect(container.querySelector(".animate-spin")).not.toBeInTheDocument();
    expect(api.dashboards.list).toHaveBeenCalledWith("proj-1");
  });

  it("shows empty state when no dashboards", async () => {
    vi.mocked(api.dashboards.list).mockResolvedValue([]);
    await renderList();
    await waitFor(() => {
      expect(screen.getByText("No dashboards yet")).toBeInTheDocument();
    });
  });

  it("renders dashboard names", async () => {
    vi.mocked(api.dashboards.list).mockResolvedValue([
      makeDashboard({ id: "a", title: "First" }),
      makeDashboard({ id: "b", title: "Second" }),
    ]);
    await renderList();
    await waitFor(() => {
      expect(screen.getByText("First")).toBeInTheDocument();
    });
    expect(screen.getByText("Second")).toBeInTheDocument();
  });

  it("opens DashboardBuilder when createRequested is true", async () => {
    vi.mocked(api.dashboards.list).mockResolvedValue([]);
    const { DashboardList } = await import("@/components/dashboards/DashboardList");
    render(<DashboardList createRequested={true} onCreateHandled={() => {}} />);
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-builder")).toBeInTheDocument();
    });
  });

  it("shows a delete button when the caller can edit", async () => {
    vi.mocked(api.dashboards.list).mockResolvedValue([
      makeDashboard({ id: "d1", title: "Alpha" }),
    ]);
    await renderList();
    await waitFor(() => {
      expect(screen.getByText("Alpha")).toBeInTheDocument();
    });
    expect(screen.getByLabelText("Delete dashboard")).toBeInTheDocument();
  });

  it("hides the delete button for viewers", async () => {
    mockState.userRole = "viewer";
    vi.mocked(api.dashboards.list).mockResolvedValue([
      makeDashboard({ id: "d1", title: "Alpha" }),
    ]);
    await renderList();
    await waitFor(() => {
      expect(screen.getByText("Alpha")).toBeInTheDocument();
    });
    expect(screen.queryByLabelText("Delete dashboard")).not.toBeInTheDocument();
  });

  it("confirms, deletes, removes the row and toasts success", async () => {
    vi.mocked(api.dashboards.list).mockResolvedValue([
      makeDashboard({ id: "d1", title: "Alpha" }),
      makeDashboard({ id: "d2", title: "Beta" }),
    ]);
    vi.mocked(api.dashboards.delete).mockResolvedValue({ ok: true });
    await renderList();
    await waitFor(() => {
      expect(screen.getByText("Alpha")).toBeInTheDocument();
    });

    const deleteButtons = screen.getAllByLabelText("Delete dashboard");
    await userEvent.click(deleteButtons[0]);

    expect(confirmAction).toHaveBeenCalledWith("Delete this dashboard?", {
      destructive: true,
    });

    await waitFor(() => {
      expect(api.dashboards.delete).toHaveBeenCalledWith("d1");
    });
    await waitFor(() => {
      expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(mockPush).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith("Dashboard deleted", "success");
  });

  it("does not delete when the confirm is cancelled", async () => {
    vi.mocked(confirmAction).mockResolvedValue(false);
    vi.mocked(api.dashboards.list).mockResolvedValue([
      makeDashboard({ id: "d1", title: "Alpha" }),
    ]);
    await renderList();
    await waitFor(() => {
      expect(screen.getByText("Alpha")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByLabelText("Delete dashboard"));

    await waitFor(() => {
      expect(confirmAction).toHaveBeenCalled();
    });
    expect(api.dashboards.delete).not.toHaveBeenCalled();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
  });

  it("toasts an error and keeps the row when delete fails", async () => {
    vi.mocked(api.dashboards.list).mockResolvedValue([
      makeDashboard({ id: "d1", title: "Alpha" }),
    ]);
    vi.mocked(api.dashboards.delete).mockRejectedValue(new Error("boom"));
    await renderList();
    await waitFor(() => {
      expect(screen.getByText("Alpha")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByLabelText("Delete dashboard"));

    await waitFor(() => {
      expect(toast).toHaveBeenCalledWith("Failed to delete dashboard", "error");
    });
    expect(screen.getByText("Alpha")).toBeInTheDocument();
  });
});
