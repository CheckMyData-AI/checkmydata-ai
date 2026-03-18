import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useAppStore } from "@/stores/app-store";
import type { Project } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    projects: {
      list: vi.fn().mockResolvedValue([]),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
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
    expect(screen.getByText("New")).toBeInTheDocument();
  });

  it("shows New button to create a project", async () => {
    await renderSelector();
    const btn = screen.getByText("New");
    expect(btn).toBeInTheDocument();
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
    await renderSelector();
    await userEvent.click(screen.getByText("New"));

    expect(screen.getByPlaceholderText("Project name")).toBeInTheDocument();
  });

  it("empty state shows no project items", async () => {
    (api.projects.list as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    useAppStore.setState({ projects: [] });

    await renderSelector();
    expect(screen.queryByRole("button", { name: /Alpha/i })).not.toBeInTheDocument();
    expect(screen.getByText("New")).toBeInTheDocument();
  });
});
