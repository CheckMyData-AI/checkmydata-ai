import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import type { Dashboard, SavedNote } from "@/lib/api";
import DashboardPage from "@/app/dashboard/[id]/page";

const dashboardsGetMock = vi.fn();
const notesGetMock = vi.fn();
const notesExecuteMock = vi.fn();
const toastMock = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "d1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/stores/toast-store", () => ({
  toast: (...a: unknown[]) => toastMock(...a),
}));

vi.mock("@/components/auth/AuthGate", () => ({
  AuthGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/ui/Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

vi.mock("@/lib/api", () => ({
  api: {
    dashboards: { get: (...a: unknown[]) => dashboardsGetMock(...a) },
    notes: {
      get: (...a: unknown[]) => notesGetMock(...a),
      execute: (...a: unknown[]) => notesExecuteMock(...a),
    },
  },
}));

function makeDashboard(): Dashboard {
  return {
    id: "d1",
    project_id: "p1",
    creator_id: "u1",
    title: "Sales",
    layout_json: JSON.stringify({ columns: 2 }),
    cards_json: JSON.stringify([{ note_id: "n1" }, { note_id: "n2" }]),
    is_shared: true,
    created_at: null,
    updated_at: null,
    user_role: "viewer",
  };
}

function makeNote(id: string): SavedNote {
  return {
    id,
    project_id: "p1",
    user_id: "u1",
    connection_id: "c1",
    title: `Note ${id}`,
    comment: null,
    sql_query: "SELECT 1",
    answer_text: null,
    visualization_json: null,
    last_result_json: null,
    is_shared: true,
    shared_by: null,
    last_executed_at: null,
    created_at: null,
    updated_at: null,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  dashboardsGetMock.mockResolvedValue(makeDashboard());
  notesGetMock.mockImplementation((id: string) => Promise.resolve(makeNote(id)));
});

describe("Shared dashboard Refresh All (SCN-084)", () => {
  it("reports the real per-card counts instead of a blanket success toast", async () => {
    // n1 refreshes cleanly; n2 fails.
    notesExecuteMock
      .mockResolvedValueOnce({ id: "n1", error: null, last_result_json: null, last_executed_at: null })
      .mockResolvedValueOnce({ id: "n2", error: "boom", last_result_json: null, last_executed_at: null });

    render(<DashboardPage />);

    const refreshBtn = await screen.findByRole("button", { name: /Refresh All/i });
    fireEvent.click(refreshBtn);

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith("Refreshed: 1 succeeded, 1 failed", "error"),
    );
    // The old dishonest "All cards refreshed" message must never fire.
    expect(toastMock).not.toHaveBeenCalledWith("All cards refreshed", "info");
  });

  it("reports an all-success refresh as info", async () => {
    notesExecuteMock.mockResolvedValue({
      id: "n",
      error: null,
      last_result_json: null,
      last_executed_at: null,
    });

    render(<DashboardPage />);

    const refreshBtn = await screen.findByRole("button", { name: /Refresh All/i });
    fireEvent.click(refreshBtn);

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith("Refreshed: 2 succeeded", "info"),
    );
  });
});
