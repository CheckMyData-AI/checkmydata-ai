import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ProjectInvite, ProjectMember } from "@/lib/api";

const mockListInvites = vi.fn<() => Promise<ProjectInvite[]>>();
const mockListMembers = vi.fn<() => Promise<ProjectMember[]>>();
const mockCreateInvite = vi.fn();
const mockRevoke = vi.fn();
const mockResend = vi.fn();
const mockRemoveMember = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    invites: {
      list: (...args: unknown[]) => mockListInvites(...(args as [])),
      listMembers: (...args: unknown[]) => mockListMembers(...(args as [])),
      create: (...args: unknown[]) => mockCreateInvite(...(args as [])),
      revoke: (...args: unknown[]) => mockRevoke(...(args as [])),
      resend: (...args: unknown[]) => mockResend(...(args as [])),
      removeMember: (...args: unknown[]) => mockRemoveMember(...(args as [])),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

vi.mock("@/components/ui/ConfirmModal", () => ({
  confirmAction: vi.fn().mockResolvedValue(true),
}));

vi.mock("@/components/ui/Spinner", () => ({
  Spinner: () => <div data-testid="spinner">Loading...</div>,
}));

function makeMember(overrides: Partial<ProjectMember> = {}): ProjectMember {
  return {
    id: "mem1",
    project_id: "proj1",
    user_id: "u1",
    role: "owner",
    email: "owner@test.com",
    display_name: "Owner",
    ...overrides,
  };
}

function makeInvite(overrides: Partial<ProjectInvite> = {}): ProjectInvite {
  return {
    id: "inv1",
    project_id: "proj1",
    email: "invited@test.com",
    role: "editor",
    status: "pending",
    invited_by: "u1",
    created_at: null,
    accepted_at: null,
    project_name: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockListInvites.mockResolvedValue([]);
  mockListMembers.mockResolvedValue([]);
  mockResend.mockResolvedValue({ ok: true });
  mockRevoke.mockResolvedValue({ ok: true });
  mockRemoveMember.mockResolvedValue({ ok: true });
});

async function renderInviteManager() {
  const { InviteManager } = await import(
    "@/components/projects/InviteManager"
  );
  return render(
    <InviteManager projectId="proj1" onClose={vi.fn()} />,
  );
}

describe("InviteManager", () => {
  it("renders invite section", async () => {
    await renderInviteManager();
    await waitFor(() => {
      expect(screen.getByText("Manage Access")).toBeInTheDocument();
    });
  });

  it("shows email input and role selector", async () => {
    await renderInviteManager();
    expect(screen.getByPlaceholderText("Email address")).toBeInTheDocument();
    const roleSelect = screen.getByDisplayValue("Editor");
    expect(roleSelect).toBeInTheDocument();
  });

  it("invite button present", async () => {
    await renderInviteManager();
    expect(screen.getByText("Invite")).toBeInTheDocument();
  });

  it("members list renders items", async () => {
    mockListMembers.mockResolvedValue([
      makeMember({ id: "m1", email: "alice@test.com", role: "owner" }),
      makeMember({
        id: "m2",
        user_id: "u2",
        email: "bob@test.com",
        role: "editor",
        display_name: "Bob",
      }),
    ]);

    await renderInviteManager();
    await waitFor(() => {
      expect(screen.getByText("alice@test.com")).toBeInTheDocument();
      expect(screen.getByText("Bob")).toBeInTheDocument();
    });
  });

  it("remove button per member except owner", async () => {
    mockListMembers.mockResolvedValue([
      makeMember({ id: "m1", email: "alice@test.com", role: "owner" }),
      makeMember({
        id: "m2",
        user_id: "u2",
        email: "bob@test.com",
        role: "editor",
      }),
    ]);

    await renderInviteManager();
    await waitFor(() => {
      expect(screen.getByText("bob@test.com")).toBeInTheDocument();
    });

    const removeButtons = screen.getAllByText("Remove");
    expect(removeButtons).toHaveLength(1);
  });

  it("clicking remove calls removeMember API", async () => {
    mockListMembers.mockResolvedValue([
      makeMember({ id: "m1", email: "alice@test.com", role: "owner" }),
      makeMember({
        id: "m2",
        user_id: "u2",
        email: "bob@test.com",
        role: "editor",
      }),
    ]);

    await renderInviteManager();
    await waitFor(() => {
      expect(screen.getByText("bob@test.com")).toBeInTheDocument();
    });

    const removeBtn = screen.getByText("Remove");
    await userEvent.click(removeBtn);
    await waitFor(() => {
      expect(mockRemoveMember).toHaveBeenCalledWith("proj1", "u2");
    });
  });

  it("pending invites shown", async () => {
    mockListInvites.mockResolvedValue([
      makeInvite({ id: "inv1", email: "pending@test.com", status: "pending" }),
    ]);

    await renderInviteManager();
    await waitFor(() => {
      expect(screen.getByText(/Pending Invites/)).toBeInTheDocument();
      expect(screen.getByText("pending@test.com")).toBeInTheDocument();
    });
  });

  it("resend button shown for each pending invite", async () => {
    mockListInvites.mockResolvedValue([
      makeInvite({ id: "inv1", email: "a@test.com", status: "pending" }),
      makeInvite({ id: "inv2", email: "b@test.com", status: "pending" }),
    ]);

    await renderInviteManager();
    await waitFor(() => {
      const resendButtons = screen.getAllByText("Resend");
      expect(resendButtons).toHaveLength(2);
    });
  });

  it("clicking resend calls resend API", async () => {
    mockListInvites.mockResolvedValue([
      makeInvite({ id: "inv1", email: "resend@test.com", status: "pending" }),
    ]);

    await renderInviteManager();
    await waitFor(() => {
      expect(screen.getByText("resend@test.com")).toBeInTheDocument();
    });

    const resendBtn = screen.getByText("Resend");
    await userEvent.click(resendBtn);
    await waitFor(() => {
      expect(mockResend).toHaveBeenCalledWith("proj1", "inv1");
    });
  });

  it("delete button shown for each pending invite", async () => {
    mockListInvites.mockResolvedValue([
      makeInvite({ id: "inv1", email: "a@test.com", status: "pending" }),
    ]);

    await renderInviteManager();
    await waitFor(() => {
      expect(screen.getByText("Delete")).toBeInTheDocument();
    });
  });

  it("clicking delete calls revoke API", async () => {
    mockListInvites.mockResolvedValue([
      makeInvite({ id: "inv1", email: "del@test.com", status: "pending" }),
    ]);

    await renderInviteManager();
    await waitFor(() => {
      expect(screen.getByText("del@test.com")).toBeInTheDocument();
    });

    const deleteBtn = screen.getByText("Delete");
    await userEvent.click(deleteBtn);
    await waitFor(() => {
      expect(mockRevoke).toHaveBeenCalledWith("proj1", "inv1");
    });
  });

  it("shows relative time for pending invites with created_at", async () => {
    const recent = new Date(Date.now() - 3600_000).toISOString();
    mockListInvites.mockResolvedValue([
      makeInvite({
        id: "inv1",
        email: "time@test.com",
        status: "pending",
        created_at: recent,
      }),
    ]);

    await renderInviteManager();
    await waitFor(() => {
      expect(screen.getByText(/Sent 1h ago/)).toBeInTheDocument();
    });
  });

  it("shows member count in section header", async () => {
    mockListMembers.mockResolvedValue([
      makeMember({ id: "m1", email: "a@t.com", role: "owner" }),
      makeMember({ id: "m2", user_id: "u2", email: "b@t.com", role: "editor" }),
    ]);

    await renderInviteManager();
    await waitFor(() => {
      expect(screen.getByText("Members (2)")).toBeInTheDocument();
    });
  });
});
