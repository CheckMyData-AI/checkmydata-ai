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

function makeDashboard(cards?: unknown[]): Dashboard {
  return {
    id: "d1",
    project_id: "p1",
    creator_id: "u1",
    title: "Sales",
    layout_json: JSON.stringify({ columns: 2 }),
    cards_json: JSON.stringify(cards ?? [{ note_id: "n1" }, { note_id: "n2" }]),
    is_shared: true,
    created_at: null,
    updated_at: null,
    user_role: "viewer",
  };
}

function makeNote(id: string, over: Partial<SavedNote> = {}): SavedNote {
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
    ...over,
  };
}

const DAY = 86_400_000;
const agoIso = (ms: number) => new Date(Date.now() - ms).toISOString();

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

describe("Dashboard card freshness (SCN-084)", () => {
  it("says what the timestamp measures instead of a bare relative age", async () => {
    dashboardsGetMock.mockResolvedValue(makeDashboard([{ note_id: "n1" }]));
    notesGetMock.mockResolvedValue(makeNote("n1", { last_executed_at: agoIso(3 * DAY) }));

    render(<DashboardPage />);

    // A bare "3d ago" beside a title cannot be told apart from "edited 3d ago";
    // the header's own "Updated …" measures the dashboard, not the data.
    expect(await screen.findByText(/Data from 3d ago/i)).toBeTruthy();
  });

  it("names a never-executed card rather than printing a relative age for it", async () => {
    dashboardsGetMock.mockResolvedValue(makeDashboard([{ note_id: "n1" }]));
    notesGetMock.mockResolvedValue(makeNote("n1", { last_executed_at: null }));

    render(<DashboardPage />);

    expect(await screen.findByText(/Never run/i)).toBeTruthy();
  });

  it("marks a card late only when it declared a refresh interval it is missing", async () => {
    // Both cards carry data three days old. Only the second one promised freshness,
    // and age alone cannot tell the two apart — which is the whole defect.
    dashboardsGetMock.mockResolvedValue(
      makeDashboard([{ note_id: "quiet" }, { note_id: "promised", refresh_interval: 300 }]),
    );
    notesGetMock.mockImplementation((id: string) =>
      Promise.resolve(makeNote(id, { last_executed_at: agoIso(3 * DAY) })),
    );
    notesExecuteMock.mockResolvedValue({ id: "promised", error: null });

    render(<DashboardPage />);

    const late = await screen.findAllByText(/not refreshing/i);
    expect(late).toHaveLength(1);
    expect(late[0].closest("[data-note-id]")?.getAttribute("data-note-id")).toBe("promised");
  });

  it("runs an overdue interval card on open instead of waiting a full interval", async () => {
    dashboardsGetMock.mockResolvedValue(
      makeDashboard([{ note_id: "overdue", refresh_interval: 300 }]),
    );
    notesGetMock.mockImplementation((id: string) =>
      Promise.resolve(makeNote(id, { last_executed_at: agoIso(3 * DAY) })),
    );
    notesExecuteMock.mockResolvedValue({ id: "overdue", error: null });

    render(<DashboardPage />);

    // setInterval fires first only after one full period, and the load path merely
    // reads the stored snapshot — so without this the promise is a lie for 5 minutes.
    await waitFor(() => expect(notesExecuteMock).toHaveBeenCalledWith("overdue"));
  });

  it("leaves a card alone when its data is younger than its declared interval", async () => {
    dashboardsGetMock.mockResolvedValue(
      makeDashboard([{ note_id: "fresh", refresh_interval: 3600 }]),
    );
    notesGetMock.mockImplementation((id: string) =>
      Promise.resolve(makeNote(id, { last_executed_at: agoIso(60_000) })),
    );

    render(<DashboardPage />);

    await screen.findByText(/Data from 1m ago/i);
    expect(notesExecuteMock).not.toHaveBeenCalled();
  });

  it("shows a failed refresh on the card instead of swallowing it", async () => {
    dashboardsGetMock.mockResolvedValue(
      makeDashboard([{ note_id: "n1", refresh_interval: 300 }]),
    );
    notesGetMock.mockImplementation((id: string) =>
      Promise.resolve(makeNote(id, { last_executed_at: agoIso(3 * DAY) })),
    );
    notesExecuteMock.mockResolvedValue({ id: "n1", error: "relation \"orders\" does not exist" });

    render(<DashboardPage />);

    // The old code did `catch { /* */ }` and `if (!res.error)`, so a card whose query
    // started failing looked exactly like a card nobody had refreshed.
    expect(await screen.findByText(/does not exist/i)).toBeTruthy();
  });
});
