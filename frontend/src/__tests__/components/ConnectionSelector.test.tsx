import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useAppStore } from "@/stores/app-store";
import type { Connection, Project } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    connections: {
      listByProject: vi.fn().mockResolvedValue([]),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
      test: vi.fn(),
      indexDb: vi.fn(),
      indexDbStatus: vi.fn().mockResolvedValue({ is_indexed: false }),
      syncStatus: vi.fn().mockResolvedValue({ is_synced: false }),
      triggerSync: vi.fn(),
      refreshSchema: vi.fn(),
      learningsStatus: vi.fn().mockResolvedValue({ total_active: 0 }),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

vi.mock("@/components/ui/ConfirmModal", () => ({
  confirmAction: vi.fn().mockResolvedValue(true),
}));

vi.mock("@/components/ui/Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

vi.mock("@/components/ui/ActionButton", () => ({
  ActionButton: ({
    icon,
    title,
    onClick,
    disabled,
  }: {
    icon: string;
    title: string;
    onClick: (e: React.MouseEvent) => void;
    disabled?: boolean;
  }) => (
    <button
      data-testid={`action-${icon}`}
      title={title}
      onClick={onClick}
      disabled={disabled}
    >
      {icon}
    </button>
  ),
}));

vi.mock("@/components/ui/StatusDot", () => ({
  StatusDot: ({ title }: { title: string }) => (
    <span data-testid="status-dot" title={title} />
  ),
}));

vi.mock("@/components/ui/Tooltip", () => ({
  Tooltip: ({
    children,
    label,
  }: {
    children: React.ReactNode;
    label: string;
  }) => <div title={label}>{children}</div>,
}));

vi.mock("@/components/learnings/LearningsPanel", () => ({
  LearningsPanel: () => <div data-testid="learnings-panel" />,
}));

const { api } = await import("@/lib/api");

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: "proj1",
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

function makeConnection(overrides: Partial<Connection> = {}): Connection {
  return {
    id: "c1",
    project_id: "proj1",
    name: "My Postgres",
    db_type: "postgres",
    source_type: "direct",
    ssh_host: null,
    ssh_port: 22,
    ssh_user: null,
    ssh_key_id: null,
    db_host: "localhost",
    db_port: 5432,
    db_name: "testdb",
    db_user: "admin",
    is_read_only: true,
    is_active: true,
    ssh_exec_mode: false,
    ssh_command_template: null,
    ssh_pre_commands: null,
    mcp_server_command: null,
    mcp_server_url: null,
    mcp_transport_type: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  useAppStore.setState({
    sshKeys: [],
    projects: [],
    activeProject: makeProject(),
    connections: [],
    activeConnection: null,
    userRole: "owner",
  });
});

async function renderSelector() {
  const { ConnectionSelector } = await import(
    "@/components/connections/ConnectionSelector"
  );
  return render(<ConnectionSelector />);
}

describe("ConnectionSelector", () => {
  it("renders connection selector section", async () => {
    await renderSelector();
    expect(screen.getByText("New")).toBeInTheDocument();
  });

  it("shows create/add button", async () => {
    await renderSelector();
    const newBtn = screen.getByText("New");
    expect(newBtn).toBeInTheDocument();
  });

  it("connection list renders items", async () => {
    const conns = [
      makeConnection({ id: "c1", name: "Prod DB" }),
      makeConnection({ id: "c2", name: "Staging DB" }),
    ];
    useAppStore.setState({ connections: conns });

    await renderSelector();
    expect(screen.getByText("Prod DB")).toBeInTheDocument();
    expect(screen.getByText("Staging DB")).toBeInTheDocument();
  });

  it("shows DB type badge/label", async () => {
    useAppStore.setState({
      connections: [makeConnection({ id: "c1", db_type: "postgres" })],
    });

    await renderSelector();
    expect(screen.getByText("postgres")).toBeInTheDocument();
  });

  it("test button present for each connection", async () => {
    useAppStore.setState({
      connections: [makeConnection({ id: "c1", name: "DB1" })],
    });

    await renderSelector();
    const testBtn = screen.getByTitle("Test connection");
    expect(testBtn).toBeInTheDocument();
  });

  it("index DB button present when connection is active and not indexed", async () => {
    const conn = makeConnection({ id: "c1", name: "DB1" });
    useAppStore.setState({
      connections: [conn],
      activeConnection: conn,
    });

    await renderSelector();
    const idxBtn = screen.getByLabelText("Index database schema");
    expect(idxBtn).toBeInTheDocument();
  });

  it("sync button present when connection is active and indexed", async () => {
    const conn = makeConnection({ id: "c1", name: "DB1" });
    (api.connections.indexDbStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      is_indexed: true,
      active_tables: 10,
      total_tables: 12,
    });
    useAppStore.setState({
      connections: [conn],
      activeConnection: conn,
    });

    await renderSelector();
    await waitFor(() => {
      expect(screen.getByLabelText("Run Code-DB Sync")).toBeInTheDocument();
    });
  });

  it("delete button per connection", async () => {
    useAppStore.setState({
      connections: [makeConnection({ id: "c1", name: "DB1" })],
    });

    await renderSelector();
    const delBtn = screen.getByTitle("Delete connection");
    expect(delBtn).toBeInTheDocument();
  });

  it("create form has host, port, database fields", async () => {
    await renderSelector();
    await userEvent.click(screen.getByText("New"));

    expect(screen.getByPlaceholderText("Host")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Port")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Database name")).toBeInTheDocument();
  });

  it("switching DB type changes default port", async () => {
    await renderSelector();
    await userEvent.click(screen.getByText("New"));

    const typeSelect = screen.getByLabelText("Database type");
    expect(screen.getByLabelText("Database port")).toHaveValue("5432");

    fireEvent.change(typeSelect, { target: { value: "mysql" } });
    expect(screen.getByLabelText("Database port")).toHaveValue("3306");
  });
});
