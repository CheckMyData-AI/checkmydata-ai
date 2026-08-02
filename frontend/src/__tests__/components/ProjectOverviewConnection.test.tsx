/**
 * The overview's "Connection Health" card must describe the connection it
 * actually has. For an analytics source `db_type` is null, so the card used to
 * render the name followed by nothing at all, under a database icon.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { useAppStore } from "@/stores/app-store";
import type { Connection, Project } from "@/lib/api";

vi.mock("@/components/connections/ConnectionHealth", () => ({
  ConnectionHealth: () => <div data-testid="connection-health" />,
}));

vi.mock("@/components/connections/SyncStatusIndicator", () => ({
  SyncStatusIndicator: () => <div data-testid="sync-status" />,
}));

vi.mock("@/components/knowledge/KnowledgeHealthPanel", () => ({
  KnowledgeHealthPanel: () => <div data-testid="knowledge-health" />,
}));

vi.mock("@/components/usage/UsageStatsPanel", () => ({
  UsageStatsPanel: () => <div data-testid="usage-stats" />,
}));

vi.mock("@/components/home/HomeAsk", () => ({
  HomeAsk: () => <div data-testid="home-ask" />,
}));

vi.mock("@/components/ui/Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

function makeProject(): Project {
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
  };
}

function makeConnection(overrides: Partial<Connection> = {}): Connection {
  return {
    id: "c1",
    project_id: "p1",
    name: "Orders DB",
    db_type: "postgres",
    source_type: "database",
    ssh_host: null,
    ssh_port: 22,
    ssh_user: null,
    ssh_key_id: null,
    db_host: "localhost",
    db_port: 5432,
    db_name: "orders",
    db_user: "admin",
    is_read_only: true,
    is_active: true,
    ssh_exec_mode: false,
    ssh_command_template: null,
    ssh_pre_commands: null,
    mcp_server_command: null,
    mcp_server_url: null,
    mcp_transport_type: null,
    vendor_credential_id: null,
    source_config: null,
    collection_enabled: true,
    collection_hour: 3,
    ...overrides,
  };
}

async function renderOverview(connection: Connection) {
  useAppStore.setState({
    activeProject: makeProject(),
    activeConnection: connection,
    connections: [connection],
  });
  const { ProjectOverview } = await import("@/components/projects/ProjectOverview");
  return render(<ProjectOverview />);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ProjectOverview — connection labelling", () => {
  it("names the vendor of an analytics connection, not an empty db_type", async () => {
    await renderOverview(
      makeConnection({
        name: "GA4 prod",
        db_type: null,
        source_type: "ga4",
        db_port: null,
        db_name: null,
      }),
    );

    expect(screen.getByText("GA4 prod")).toBeInTheDocument();
    expect(screen.getByText("GA4")).toBeInTheDocument();
    expect(screen.queryByTestId("icon-database")).not.toBeInTheDocument();
  });

  it("still labels a database connection with its engine and icon", async () => {
    await renderOverview(makeConnection());

    expect(screen.getByText("Orders DB")).toBeInTheDocument();
    expect(screen.getByText("postgres")).toBeInTheDocument();
    expect(screen.getByTestId("icon-database")).toBeInTheDocument();
  });
});
