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
const mockUpdateMemberRole = vi.fn();
const mockTransferOwnership = vi.fn();
const mockLeaveProject = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    invites: {
      list: (...args: unknown[]) => mockListInvites(...(args as [])),
      listMembers: (...args: unknown[]) => mockListMembers(...(args as [])),
      create: (...args: unknown[]) => mockCreateInvite(...(args as [])),
      revoke: (...args: unknown[]) => mockRevoke(...(args as [])),
      resend: (...args: unknown[]) => mockResend(...(args as [])),
      removeMember: (...args: unknown[]) => mockRemoveMember(...(args as [])),
      updateMemberRole: (...args: unknown[]) => mockUpdateMemberRole(...(args as [])),
      transferOwnership: (...args: unknown[]) => mockTransferOwnership(...(args as [])),
      leaveProject: (...args: unknown[]) => mockLeaveProject(...(args as [])),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

// The viewer's own role decides whether the transfer action exists at all, and it is
// read from the members list itself rather than a new prop (two call sites render this
// component; a required prop would make them disagree).
let currentUserId = "u1";
vi.mock("@/stores/auth-store", () => ({
  // `AuthUser` carries `id`, not `user_id` — a mock that invents the wrong field
  // passes against code reading the wrong field and fails only in production.
  useAuthStore: { getState: () => ({ user: { id: currentUserId } }) },
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
  currentUserId = "u1";
  mockTransferOwnership.mockResolvedValue(undefined);
  mockLeaveProject.mockResolvedValue(undefined);
  mockUpdateMemberRole.mockResolvedValue({
    id: "m2",
    project_id: "proj1",
    user_id: "u2",
    role: "viewer",
    email: "bob@test.com",
    display_name: "Bob",
  });
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

  it("shows role dropdown for non-owner members", async () => {
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
      expect(screen.getByText("Bob")).toBeInTheDocument();
    });

    const roleSelect = screen.getByLabelText("Change role for bob@test.com");
    expect(roleSelect).toBeInTheDocument();
    expect(roleSelect).toHaveValue("editor");
  });

  it("owner member shows static badge, not dropdown", async () => {
    mockListMembers.mockResolvedValue([
      makeMember({ id: "m1", email: "alice@test.com", role: "owner" }),
    ]);

    await renderInviteManager();
    await waitFor(() => {
      expect(screen.getByText("alice@test.com")).toBeInTheDocument();
    });

    expect(screen.getByText("owner")).toBeInTheDocument();
    expect(screen.queryByLabelText("Change role for alice@test.com")).not.toBeInTheDocument();
  });

  it("changing role calls updateMemberRole API", async () => {
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
      expect(screen.getByText("Bob")).toBeInTheDocument();
    });

    const roleSelect = screen.getByLabelText("Change role for bob@test.com");
    await userEvent.selectOptions(roleSelect, "viewer");
    await waitFor(() => {
      expect(mockUpdateMemberRole).toHaveBeenCalledWith("proj1", "u2", "viewer");
    });
  });
});

describe("Ownership transfer (F-PROJ-10)", () => {
  const owner = () => makeMember({ id: "m1", user_id: "u1", role: "owner", email: "owner@test.com" });
  const editor = () =>
    makeMember({ id: "m2", user_id: "u2", role: "editor", email: "bob@test.com", display_name: "Bob" });

  it("offers the owner a way to hand the project over", async () => {
    // Before this the owner was permanent: no role the API accepted made anyone else
    // an owner, so an owner leaving stranded the workspace with no in-product fix.
    mockListMembers.mockResolvedValue([owner(), editor()]);
    await renderInviteManager();
    expect(await screen.findByRole("button", { name: /make owner: Bob/i })).toBeTruthy();
  });

  it("does not offer it on the owner's own row", async () => {
    mockListMembers.mockResolvedValue([owner(), editor()]);
    await renderInviteManager();
    await screen.findByText("bob@test.com");
    const buttons = screen.getAllByRole("button", { name: /make owner/i });
    expect(buttons).toHaveLength(1);
  });

  it("hides it from a non-owner", async () => {
    currentUserId = "u2"; // Bob, an editor
    mockListMembers.mockResolvedValue([owner(), editor()]);
    await renderInviteManager();
    await screen.findByText("owner@test.com");
    expect(screen.queryByRole("button", { name: /make owner/i })).toBeNull();
  });

  it("names the consequence before doing it, and it is not reversible by the actor", async () => {
    const { confirmAction } = await import("@/components/ui/ConfirmModal");
    mockListMembers.mockResolvedValue([owner(), editor()]);
    await renderInviteManager();

    await userEvent.click(await screen.findByRole("button", { name: /make owner/i }));

    expect(confirmAction).toHaveBeenCalled();
    const [message, opts] = (confirmAction as unknown as { mock: { calls: unknown[][] } }).mock
      .calls[0] as [string, { detail?: string }];
    const said = `${message} ${opts?.detail ?? ""}`;
    expect(said).toMatch(/Bob|bob@test\.com/);
    // The actor is demoted to editor and cannot take it back — a confirm that does not
    // say so is asking someone to agree to something they have not been told.
    expect(said).toMatch(/editor/i);
    expect(said).toMatch(/cannot|can't|only the new owner/i);
  });

  it("calls the transfer endpoint and reloads the members list", async () => {
    mockListMembers.mockResolvedValue([owner(), editor()]);
    await renderInviteManager();

    await userEvent.click(await screen.findByRole("button", { name: /make owner/i }));

    await waitFor(() => expect(mockTransferOwnership).toHaveBeenCalledWith("proj1", "u2"));
    // Both rows change at once, so a local patch would show two owners or none;
    // re-reading is the only honest refresh.
    await waitFor(() => expect(mockListMembers.mock.calls.length).toBeGreaterThan(1));
  });

  it("does nothing when the confirm is declined", async () => {
    const { confirmAction } = await import("@/components/ui/ConfirmModal");
    (confirmAction as unknown as { mockResolvedValue: (v: boolean) => void }).mockResolvedValue(
      false,
    );
    mockListMembers.mockResolvedValue([owner(), editor()]);
    await renderInviteManager();

    await userEvent.click(await screen.findByRole("button", { name: /make owner/i }));

    expect(mockTransferOwnership).not.toHaveBeenCalled();
  });
});

describe("Leave project (SCN-127, F-PROJ-12)", () => {
  const owner = () => makeMember({ id: "m1", user_id: "u1", role: "owner", email: "owner@test.com" });
  const bob = () =>
    makeMember({ id: "m2", user_id: "u2", role: "editor", email: "bob@test.com", display_name: "Bob" });

  it("offers a way out to a non-owner member", async () => {
    // Before F-PROJ-12 there was none: only an owner could remove a member, so a person
    // who no longer needed the project stayed in it until someone else acted.
    currentUserId = "u2";
    mockListMembers.mockResolvedValue([owner(), bob()]);
    await renderInviteManager();
    expect(await screen.findByRole("button", { name: /leave project/i })).toBeTruthy();
  });

  it("does not offer it to the owner", async () => {
    // Leaving would strand the workspace — the state SCN-126 exists to prevent. The
    // backend refuses with 400; the button is absent so nobody is invited to try.
    currentUserId = "u1";
    mockListMembers.mockResolvedValue([owner(), bob()]);
    await renderInviteManager();
    await screen.findByText("bob@test.com");
    expect(screen.queryByRole("button", { name: /leave project/i })).toBeNull();
  });

  it("names the consequence before doing it", async () => {
    const { confirmAction } = await import("@/components/ui/ConfirmModal");
    (confirmAction as unknown as { mockResolvedValue: (v: boolean) => void }).mockResolvedValue(true);
    currentUserId = "u2";
    mockListMembers.mockResolvedValue([owner(), bob()]);
    await renderInviteManager();

    await userEvent.click(await screen.findByRole("button", { name: /leave project/i }));

    const [message, opts] = (confirmAction as unknown as { mock: { calls: unknown[][] } })
      .mock.calls[0] as [string, { detail?: string }];
    const said = `${message} ${opts?.detail ?? ""}`;
    expect(said).toMatch(/lose access|no longer/i);
    expect(said).toMatch(/owner|invite/i);
  });

  it("calls the endpoint with no user id and reloads", async () => {
    const { confirmAction } = await import("@/components/ui/ConfirmModal");
    (confirmAction as unknown as { mockResolvedValue: (v: boolean) => void }).mockResolvedValue(true);
    currentUserId = "u2";
    mockListMembers.mockResolvedValue([owner(), bob()]);
    await renderInviteManager();

    await userEvent.click(await screen.findByRole("button", { name: /leave project/i }));

    // One argument only: the request cannot name anyone else.
    await waitFor(() => expect(mockLeaveProject).toHaveBeenCalledWith("proj1"));
  });

  it("does nothing when the confirm is declined", async () => {
    const { confirmAction } = await import("@/components/ui/ConfirmModal");
    (confirmAction as unknown as { mockResolvedValue: (v: boolean) => void }).mockResolvedValue(false);
    currentUserId = "u2";
    mockListMembers.mockResolvedValue([owner(), bob()]);
    await renderInviteManager();

    await userEvent.click(await screen.findByRole("button", { name: /leave project/i }));
    expect(mockLeaveProject).not.toHaveBeenCalled();
  });

  it("surfaces the server's refusal rather than pretending it worked", async () => {
    const { confirmAction } = await import("@/components/ui/ConfirmModal");
    (confirmAction as unknown as { mockResolvedValue: (v: boolean) => void }).mockResolvedValue(true);
    mockLeaveProject.mockRejectedValue(new Error("The project owner cannot leave"));
    currentUserId = "u2";
    mockListMembers.mockResolvedValue([owner(), bob()]);
    await renderInviteManager();

    const { toast } = await import("@/stores/toast-store");

    await userEvent.click(await screen.findByRole("button", { name: /leave project/i }));
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.stringContaining("owner cannot leave"),
        "error",
      ),
    );
  });
});
