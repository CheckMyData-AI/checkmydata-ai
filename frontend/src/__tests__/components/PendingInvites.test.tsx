import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ProjectInvite } from "@/lib/api";

const mockListPending = vi.fn<() => Promise<ProjectInvite[]>>();
const mockDecline = vi.fn();
const mockAccept = vi.fn();
const mockProjectsList = vi.fn();
const mockToast = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    invites: {
      listPending: (...args: unknown[]) => mockListPending(...(args as [])),
      decline: (...args: unknown[]) => mockDecline(...(args as [])),
      accept: (...args: unknown[]) => mockAccept(...(args as [])),
    },
    projects: {
      list: (...args: unknown[]) => mockProjectsList(...(args as [])),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: (...args: unknown[]) => mockToast(...(args as [])),
}));

vi.mock("@/stores/app-store", () => ({
  useAppStore: (selector: (s: { setProjects: () => void }) => unknown) =>
    selector({ setProjects: vi.fn() }),
}));

vi.mock("@/components/ui/Spinner", () => ({
  Spinner: () => <div data-testid="spinner">Loading...</div>,
}));

function makeInvite(overrides: Partial<ProjectInvite> = {}): ProjectInvite {
  return {
    id: "inv1",
    project_id: "proj1",
    email: "me@test.com",
    role: "editor",
    status: "pending",
    invited_by: "u1",
    created_at: null,
    accepted_at: null,
    project_name: "Acme",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockListPending.mockResolvedValue([]);
  mockDecline.mockResolvedValue({ ok: true });
  mockProjectsList.mockResolvedValue([]);
});

async function renderPendingInvites() {
  const { PendingInvites } = await import("@/components/invites/PendingInvites");
  return render(<PendingInvites />);
}

describe("PendingInvites decline", () => {
  it("renders a Decline action per pending invite", async () => {
    mockListPending.mockResolvedValue([makeInvite()]);
    await renderPendingInvites();
    await waitFor(() => {
      expect(screen.getByLabelText("Decline invitation to Acme")).toBeInTheDocument();
    });
  });

  it("declining calls the API, removes the row, and shows a success toast", async () => {
    mockListPending.mockResolvedValue([makeInvite({ id: "inv1", project_name: "Acme" })]);
    await renderPendingInvites();
    const declineBtn = await screen.findByLabelText("Decline invitation to Acme");

    await userEvent.click(declineBtn);

    await waitFor(() => {
      expect(mockDecline).toHaveBeenCalledWith("inv1");
    });
    await waitFor(() => {
      expect(mockToast).toHaveBeenCalledWith("Invite declined", "success");
    });
    // The banner returns null once the last invite is removed.
    expect(screen.queryByLabelText("Decline invitation to Acme")).not.toBeInTheDocument();
    // Declining must not accept the invite.
    expect(mockAccept).not.toHaveBeenCalled();
  });

  it("shows an error toast and keeps the row when decline fails", async () => {
    mockListPending.mockResolvedValue([makeInvite({ id: "inv1", project_name: "Acme" })]);
    mockDecline.mockRejectedValue(new Error("boom"));
    await renderPendingInvites();
    const declineBtn = await screen.findByLabelText("Decline invitation to Acme");

    await userEvent.click(declineBtn);

    await waitFor(() => {
      expect(mockToast).toHaveBeenCalledWith("boom", "error");
    });
    // The invite row survives a failed decline.
    expect(screen.getByLabelText("Decline invitation to Acme")).toBeInTheDocument();
  });
});
