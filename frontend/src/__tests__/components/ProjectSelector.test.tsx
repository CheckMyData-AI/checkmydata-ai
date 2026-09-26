import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useAppStore } from "@/stores/app-store";
import { useAuthStore } from "@/stores/auth-store";
import type { Project } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    projects: {
      list: vi.fn().mockResolvedValue([]),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
      requestAccess: vi.fn().mockResolvedValue({ ok: true }),
    },
    connections: { listByProject: vi.fn().mockResolvedValue([]) },
    chat: { listSessions: vi.fn().mockResolvedValue([]) },
    repos: { checkAccess: vi.fn() },
    sshKeys: { list: vi.fn().mockResolvedValue([]) },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

vi.mock("@/components/projects/RequestAccessModal", () => ({
  RequestAccessModal: ({ open, onClose }: { open: boolean; onClose: () => void }) =>
    open ? <div data-testid="request-access-modal"><button onClick={onClose}>Close</button></div> : null,
}));

vi.mock("@/components/ui/ConfirmModal", () => ({
  confirmAction: vi.fn().mockResolvedValue(true),
}));

vi.mock("@/components/ui/Spinner", () => ({
  Spinner: () => <div data-testid="spinner">Loading...</div>,
}));

vi.mock("@/components/ui/Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

vi.mock("@/components/ui/ActionButton", () => ({
  ActionButton: ({
    icon,
    title,
    onClick,
  }: {
    icon: string;
    title: string;
    onClick: (e: React.MouseEvent) => void;
  }) => (
    <button data-testid={`action-${icon}`} title={title} onClick={onClick}>
      {icon}
    </button>
  ),
}));

vi.mock("@/components/ui/LlmModelSelector", () => ({
  LlmModelSelector: () => <div data-testid="llm-selector" />,
  formatProvider: (p: string) => p,
  formatModelShort: (m: string) => m,
  EMPTY_LLM: { provider: "", model: "" },
}));

vi.mock("./InviteManager", () => ({
  InviteManager: () => <div data-testid="invite-manager" />,
}));

const { api } = await import("@/lib/api");

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: "p1",
    name: "Test Project",
    description: "",
    repo_url: null,
    repo_branch: "main",
    ssh_key_id: null,
    indexing_llm_provider: null,
    indexing_llm_model: null,
    agent_llm_provider: null,
    agent_llm_model: null,
    sql_llm_provider: null,
    sql_llm_model: null,
    owner_id: "u1",
    user_role: "owner",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  useAppStore.setState({
    sshKeys: [],
    projects: [],
    activeProject: null,
    connections: [],
    activeConnection: null,
    chatSessions: [],
    activeSession: null,
    messages: [],
    isLoading: false,
    userRole: null,
  });
  useAuthStore.setState({
    user: {
      id: "u1",
      email: "test@test.com",
      display_name: "Test User",
      can_create_projects: true,
    },
    token: "test-token",
  });
  (api.projects.list as ReturnType<typeof vi.fn>).mockResolvedValue([]);
});

async function renderSelector() {
  const { ProjectSelector } = await import(
    "@/components/projects/ProjectSelector"
  );
  return render(<ProjectSelector />);
}

describe("ProjectSelector", () => {
  it("renders project selector", async () => {
    await renderSelector();
    expect(document.querySelector("[class*='px-1']")).toBeInTheDocument();
  });

  it("opens create form when createRequested is true", async () => {
    const { ProjectSelector } = await import("@/components/projects/ProjectSelector");
    const onHandled = vi.fn();
    render(<ProjectSelector createRequested={true} onCreateHandled={onHandled} />);
    expect(onHandled).toHaveBeenCalled();
    expect(screen.getByPlaceholderText("Project name")).toBeInTheDocument();
  });

  it("project list renders items", async () => {
    const projects = [
      makeProject({ id: "p1", name: "Alpha" }),
      makeProject({ id: "p2", name: "Beta" }),
    ];
    (api.projects.list as ReturnType<typeof vi.fn>).mockResolvedValue(projects);
    useAppStore.setState({ projects });

    await renderSelector();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
  });

  it("clicking project calls setActiveProject", async () => {
    const project = makeProject({ id: "p1", name: "Alpha" });
    (api.projects.list as ReturnType<typeof vi.fn>).mockResolvedValue([
      project,
    ]);
    (api.connections.listByProject as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (api.chat.listSessions as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    useAppStore.setState({ projects: [project] });

    await renderSelector();
    await userEvent.click(screen.getByText("Alpha"));

    await waitFor(() => {
      expect(useAppStore.getState().activeProject?.id).toBe("p1");
    });
  });

  it("edit button opens edit form", async () => {
    const project = makeProject({ id: "p1", name: "Alpha", user_role: "owner" });
    (api.projects.list as ReturnType<typeof vi.fn>).mockResolvedValue([project]);
    useAppStore.setState({ projects: [project] });

    await renderSelector();
    const editBtn = screen.getByTitle("Edit project");
    await userEvent.click(editBtn);

    expect(screen.getByDisplayValue("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Save Changes")).toBeInTheDocument();
  });

  it("delete button exists for each owner project", async () => {
    const project = makeProject({ id: "p1", name: "Alpha", user_role: "owner" });
    (api.projects.list as ReturnType<typeof vi.fn>).mockResolvedValue([project]);
    useAppStore.setState({ projects: [project] });

    await renderSelector();
    const deleteBtn = screen.getByTitle("Delete project");
    expect(deleteBtn).toBeInTheDocument();
  });

  it("create form has name input", async () => {
    const { ProjectSelector } = await import("@/components/projects/ProjectSelector");
    render(<ProjectSelector createRequested={true} onCreateHandled={() => {}} />);
    expect(screen.getByPlaceholderText("Project name")).toBeInTheDocument();
  });

  it("empty state shows no project items", async () => {
    (api.projects.list as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    useAppStore.setState({ projects: [] });

    await renderSelector();
    expect(screen.queryByRole("button", { name: /Alpha/i })).not.toBeInTheDocument();
  });

  it("shows request access modal for ineligible user", async () => {
    useAuthStore.setState({
      user: {
        id: "u1",
        email: "test@test.com",
        display_name: "Test User",
        can_create_projects: false,
      },
      token: "test-token",
    });
    const { ProjectSelector } = await import("@/components/projects/ProjectSelector");
    const onHandled = vi.fn();
    render(<ProjectSelector createRequested={true} onCreateHandled={onHandled} />);
    expect(onHandled).toHaveBeenCalled();
    expect(screen.getByTestId("request-access-modal")).toBeInTheDocument();
  });

  // SCN-016: a created project is entered through the same path as a picked one —
  // `setActiveProject` alone left the previous project's data under the new name.
  it("a new project does not inherit the previous project's connections or role", async () => {
    const old = makeProject({ id: "p-old", name: "Old", user_role: "viewer" });
    const created = makeProject({ id: "p-new", name: "Fresh", user_role: "owner" });
    (api.projects.create as ReturnType<typeof vi.fn>).mockResolvedValue(created);
    (api.connections.listByProject as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (api.chat.listSessions as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    useAppStore.setState({
      projects: [old],
      activeProject: old,
      userRole: "viewer",
      connections: [{ id: "c-old", name: "old-db" } as never],
      activeConnection: { id: "c-old", name: "old-db" } as never,
      chatSessions: [{ id: "s-old", project_id: "p-old", title: "old chat" } as never],
    });

    const { ProjectSelector } = await import("@/components/projects/ProjectSelector");
    render(<ProjectSelector createRequested={true} onCreateHandled={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText("Project name"), "Fresh");
    await userEvent.click(screen.getByText("Create"));

    await waitFor(() => expect(api.connections.listByProject).toHaveBeenCalledWith("p-new"));
    const state = useAppStore.getState();
    expect(state.activeProject?.id).toBe("p-new");
    expect(state.userRole).toBe("owner");
    expect(state.connections).toEqual([]);
    expect(state.activeConnection).toBeNull();
    expect(state.chatSessions.find((x) => x.id === "s-old")).toBeUndefined();
  });

  // SCN-018: every "edit the project" trigger lands in one effect; the form saves through
  // an owner-only PATCH, so a non-owner must not be handed it.
  it("an edit trigger opens the form for the owner", async () => {
    const project = makeProject({ id: "p1", name: "Alpha", user_role: "owner" });
    useAppStore.setState({ projects: [project], activeProject: project, userRole: "owner" });
    await renderSelector();
    useAppStore.getState().setTriggerProjectEdit(true);
    expect(await screen.findByText("Save Changes")).toBeInTheDocument();
  });

  it("an edit trigger does not open the form for a non-owner, and says why", async () => {
    const project = makeProject({ id: "p1", name: "Alpha", user_role: "editor" });
    useAppStore.setState({ projects: [project], activeProject: project, userRole: "editor" });
    const { toast } = await import("@/stores/toast-store");
    await renderSelector();
    useAppStore.getState().setTriggerProjectEdit(true);
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(expect.stringContaining("Only the project owner"), "info"),
    );
    expect(screen.queryByText("Save Changes")).not.toBeInTheDocument();
    expect(useAppStore.getState().triggerProjectEdit).toBe(false);
  });
});
