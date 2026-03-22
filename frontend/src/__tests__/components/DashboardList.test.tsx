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

vi.mock("@/stores/app-store", () => ({
  useAppStore: (selector: (s: { activeProject: { id: string } | null }) => unknown) =>
    selector({ activeProject: { id: "proj-1" } }),
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

vi.mock("@/components/dashboards/DashboardBuilder", () => ({
  DashboardBuilder: () => <div data-testid="dashboard-builder">Builder</div>,
}));

vi.mock("@/lib/api", () => ({
  api: {
    dashboards: {
      list: vi.fn(),
    },
  },
}));

const { api } = await import("@/lib/api");

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
});
