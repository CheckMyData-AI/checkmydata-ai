/**
 * Editing an existing analytics connection (SCN-113 follow-up).
 *
 * Nothing opened the Edit form on an analytics row before, which is exactly
 * where the two worst failures lived:
 *
 * * **H6** — the source-type select stayed editable in edit mode while only the
 *   MCP branch ever sent `source_type`. Picking "postgres" on a GA4 row posted
 *   `db_type: "postgres"` with no `source_type`, the backend merged the old
 *   `ga4` back in, and the user got a green "Connection updated" toast for a row
 *   that is now half one kind and half the other. The reverse direction flipped
 *   `source_type` to `ga4` while leaving host, database and password in place.
 * * **M2** — `source_config` was rebuilt from the two fields the form owns and
 *   the backend replaces the document wholesale, so every save silently dropped
 *   `event_names`, `currency_code` and every property after the first. Dropping
 *   `event_names` un-filters the events report: the next collection pulls the
 *   whole property.
 *
 * A connection's *kind* is therefore fixed at creation, and everything the form
 * does not own survives a round trip untouched.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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
      health: vi.fn().mockResolvedValue({ status: "healthy", latency_ms: 10 }),
      collectionStatus: vi.fn().mockResolvedValue({
        connection_id: "c1",
        source_type: "ga4",
        status: "ok",
        last_run_at: null,
        next_scheduled_hour: 3,
        pending_periods: 0,
        reports: [],
      }),
      collectNow: vi.fn().mockResolvedValue({ status: "queued" }),
    },
  },
}));

vi.mock("@/lib/api/vendor-credentials", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/vendor-credentials")>(
    "@/lib/api/vendor-credentials",
  );
  return {
    ...actual,
    vendorCredentials: {
      list: vi.fn().mockResolvedValue([]),
      create: vi.fn(),
      delete: vi.fn(),
    },
  };
});

vi.mock("@/stores/toast-store", () => ({ toast: vi.fn() }));

vi.mock("@/components/ui/ConfirmModal", () => ({
  confirmAction: vi.fn().mockResolvedValue(true),
}));

vi.mock("@/components/ui/Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

vi.mock("@/components/ui/Tooltip", () => ({
  Tooltip: ({ children, label }: { children: React.ReactNode; label: string }) => (
    <div title={label}>{children}</div>
  ),
}));

vi.mock("@/components/learnings/LearningsPanel", () => ({
  LearningsPanel: () => <div data-testid="learnings-panel" />,
}));

const { api } = await import("@/lib/api");
const { vendorCredentials } = await import("@/lib/api/vendor-credentials");

const GA4_CREDENTIAL = {
  id: "vc1",
  name: "analytics-sa",
  provider: "ga4",
  fingerprint: "abc123def4567890",
  meta: { client_email: "collector@proj.iam.gserviceaccount.com" },
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

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

function makeGa4Connection(overrides: Partial<Connection> = {}): Connection {
  return {
    id: "c1",
    project_id: "proj1",
    name: "GA4 prod",
    db_type: null,
    source_type: "ga4",
    ssh_host: null,
    ssh_port: 22,
    ssh_user: null,
    ssh_key_id: null,
    db_host: "127.0.0.1",
    db_port: null,
    db_name: null,
    db_user: null,
    is_read_only: true,
    is_active: true,
    ssh_exec_mode: false,
    ssh_command_template: null,
    ssh_pre_commands: null,
    mcp_server_command: null,
    mcp_server_url: null,
    mcp_transport_type: null,
    vendor_credential_id: "vc1",
    source_config: {
      property_ids: ["111", "222"],
      backfill_days: 30,
      event_names: ["purchase", "sign_up"],
      currency_code: "USD",
    },
    collection_enabled: true,
    collection_hour: 3,
    ...overrides,
  };
}

function makePostgresConnection(overrides: Partial<Connection> = {}): Connection {
  return {
    ...makeGa4Connection(),
    id: "c2",
    name: "Orders DB",
    db_type: "postgres",
    source_type: "database",
    db_host: "localhost",
    db_port: 5432,
    db_name: "orders",
    db_user: "admin",
    vendor_credential_id: null,
    source_config: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  (vendorCredentials.list as ReturnType<typeof vi.fn>).mockResolvedValue([GA4_CREDENTIAL]);
  (api.connections.update as ReturnType<typeof vi.fn>).mockImplementation(
    async (_id: string, updates: Record<string, unknown>) => ({
      ...makeGa4Connection(),
      ...updates,
    }),
  );
  useAppStore.setState({
    sshKeys: [],
    projects: [],
    activeProject: makeProject(),
    connections: [],
    connectionsError: null,
    activeConnection: null,
    userRole: "owner",
  });
});

async function renderList(connections: Connection[]) {
  const { ConnectionSelector } = await import(
    "@/components/connections/ConnectionSelector"
  );
  useAppStore.setState({ connections, activeConnection: connections[0] ?? null });
  return render(<ConnectionSelector />);
}

async function openEdit(connections: Connection[]) {
  const view = await renderList(connections);
  fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
  return view;
}

function updatePayload(): Record<string, unknown> {
  const calls = (api.connections.update as ReturnType<typeof vi.fn>).mock.calls;
  return calls[0][1] as Record<string, unknown>;
}

describe("Edit an analytics connection — the kind is fixed at creation (H6)", () => {
  it("offers no way to turn a GA4 connection into a database connection", async () => {
    await openEdit([makeGa4Connection()]);

    await waitFor(() =>
      expect(screen.getByLabelText("GA4 vendor credential")).toBeInTheDocument(),
    );

    // No engine picker at all: postgres/mysql/mongodb are not choices here.
    expect(screen.queryByLabelText("Database type")).not.toBeInTheDocument();
    // …and the kind is still stated, read-only, so the row is not anonymous.
    expect(screen.getByText("Source type")).toBeInTheDocument();
    expect(screen.getByTestId("connection-source-type")).toHaveTextContent(
      "Google Analytics 4",
    );
  });

  it("saves a GA4 edit as GA4 — no db_type, no host, still source_type ga4", async () => {
    await openEdit([makeGa4Connection()]);
    await waitFor(() =>
      expect(screen.getByLabelText("GA4 vendor credential")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByLabelText("Connection name"), {
      target: { value: "GA4 prod (renamed)" },
    });
    fireEvent.click(screen.getByText("Save Changes"));

    await waitFor(() => expect(api.connections.update).toHaveBeenCalledTimes(1));
    const payload = updatePayload();
    expect(payload).toMatchObject({
      name: "GA4 prod (renamed)",
      source_type: "ga4",
      vendor_credential_id: "vc1",
    });
    expect(payload).not.toHaveProperty("db_type");
    expect(payload).not.toHaveProperty("db_host");
    expect(payload).not.toHaveProperty("db_port");
    expect(payload).not.toHaveProperty("db_name");
  });

  it("offers no way to turn a database connection into GA4 or MCP", async () => {
    await openEdit([makePostgresConnection()]);

    const select = screen.getByLabelText("Database type") as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toContain("postgres");
    expect(values).toContain("mysql");
    // Both would flip source_type underneath a row that keeps its host,
    // database name and encrypted password.
    expect(values).not.toContain("ga4");
    expect(values).not.toContain("mcp");
  });

  it("saves a database edit as a database — never posts an analytics source_type", async () => {
    await openEdit([makePostgresConnection()]);

    fireEvent.change(screen.getByLabelText("Connection name"), {
      target: { value: "Orders DB (renamed)" },
    });
    fireEvent.click(screen.getByText("Save Changes"));

    await waitFor(() => expect(api.connections.update).toHaveBeenCalledTimes(1));
    const payload = updatePayload();
    expect(payload).toMatchObject({ name: "Orders DB (renamed)", db_type: "postgres" });
    expect(payload).not.toHaveProperty("source_type");
    expect(payload).not.toHaveProperty("vendor_credential_id");
    expect(payload).not.toHaveProperty("source_config");
  });
});

describe("Edit an analytics connection — source_config round trip (M2)", () => {
  it("keeps the vendor knobs the form does not own when only the name changes", async () => {
    await openEdit([makeGa4Connection()]);
    await waitFor(() =>
      expect(screen.getByLabelText("GA4 vendor credential")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByLabelText("Connection name"), {
      target: { value: "GA4 prod v2" },
    });
    fireEvent.click(screen.getByText("Save Changes"));

    await waitFor(() => expect(api.connections.update).toHaveBeenCalledTimes(1));
    const config = updatePayload().source_config as Record<string, unknown>;
    // Dropping event_names un-filters the events report on the next run.
    expect(config.event_names).toEqual(["purchase", "sign_up"]);
    expect(config.currency_code).toBe("USD");
    // The extra property is not editable here, so it must not be deleted here.
    expect(config.property_ids).toEqual(["111", "222"]);
    expect(config.backfill_days).toBe(30);
  });

  it("applies the edited property id without discarding the others", async () => {
    await openEdit([makeGa4Connection()]);
    await waitFor(() =>
      expect(screen.getByLabelText("GA4 property ID")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByLabelText("GA4 property ID"), {
      target: { value: "333" },
    });
    fireEvent.click(screen.getByText("Save Changes"));

    await waitFor(() => expect(api.connections.update).toHaveBeenCalledTimes(1));
    const config = updatePayload().source_config as Record<string, unknown>;
    expect(config.property_ids).toEqual(["333", "222"]);
    expect(config.currency_code).toBe("USD");
  });

  it("starts a brand-new GA4 connection from an empty source_config", async () => {
    const { ConnectionSelector } = await import(
      "@/components/connections/ConnectionSelector"
    );
    (api.connections.create as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeGa4Connection({ id: "c9" }),
    );
    render(<ConnectionSelector createRequested onCreateHandled={() => {}} />);

    fireEvent.change(screen.getByLabelText("Database type"), {
      target: { value: "ga4" },
    });
    await waitFor(() =>
      expect(screen.getByLabelText("GA4 vendor credential")).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText("Connection name"), {
      target: { value: "Fresh GA4" },
    });
    fireEvent.change(screen.getByLabelText("GA4 vendor credential"), {
      target: { value: "vc1" },
    });
    fireEvent.change(screen.getByLabelText("GA4 property ID"), {
      target: { value: "999" },
    });
    fireEvent.click(screen.getByText("Create Connection"));

    await waitFor(() => expect(api.connections.create).toHaveBeenCalledTimes(1));
    const payload = (api.connections.create as ReturnType<typeof vi.fn>).mock
      .calls[0][0] as Record<string, unknown>;
    expect(payload.source_config).toEqual({
      property_ids: ["999"],
      backfill_days: 30,
    });
  });
});

describe("Analytics rows skip the live health probe", () => {
  it("never asks /health for a source that can only answer 'unknown'", async () => {
    await renderList([makeGa4Connection()]);
    await waitFor(() =>
      expect(screen.getByTestId("collection-outcome")).toBeInTheDocument(),
    );
    expect(api.connections.health).not.toHaveBeenCalled();
  });

  it("still asks /health for a database connection", async () => {
    await renderList([makePostgresConnection()]);
    await waitFor(() => expect(api.connections.health).toHaveBeenCalledWith("c2"));
  });
});
