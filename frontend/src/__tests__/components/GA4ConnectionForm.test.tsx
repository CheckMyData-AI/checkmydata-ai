/**
 * SCN-113 — add a Google Analytics 4 connection.
 *
 * The GA4 branch of ConnectionSelector: picking the source type swaps the whole
 * DB/SSH form out for the analytics fields, and a submit without a credential is
 * refused loudly instead of posting a half-formed connection.
 */
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
      health: vi.fn().mockResolvedValue({ status: "healthy", latency_ms: 10 }),
      collectionStatus: vi.fn().mockResolvedValue({
        status: null,
        last_run: null,
        next_scheduled_hour: 3,
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
const { toast } = await import("@/stores/toast-store");

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

beforeEach(() => {
  vi.clearAllMocks();
  (vendorCredentials.list as ReturnType<typeof vi.fn>).mockResolvedValue([GA4_CREDENTIAL]);
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

async function renderForm() {
  const { ConnectionSelector } = await import(
    "@/components/connections/ConnectionSelector"
  );
  const view = render(<ConnectionSelector createRequested onCreateHandled={() => {}} />);
  return view;
}

function selectGa4() {
  fireEvent.change(screen.getByLabelText("Database type"), { target: { value: "ga4" } });
}

describe("ConnectionSelector — Google Analytics 4 source (SCN-113)", () => {
  it("offers Google Analytics 4 in the source-type select", async () => {
    await renderForm();
    const select = screen.getByLabelText("Database type") as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toContain("ga4");
    expect(screen.getByRole("option", { name: "Google Analytics 4" })).toBeInTheDocument();
  });

  it("hides the DB/SSH fields and reveals the credential + property inputs", async () => {
    await renderForm();
    expect(screen.getByLabelText("Database host")).toBeInTheDocument();

    selectGa4();

    // DB + SSH + read-only are all gone: a GA4 property has no host or tunnel.
    expect(screen.queryByLabelText("Database host")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Database port")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Database name")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Database username")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("SSH host")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("SSH key")).not.toBeInTheDocument();
    expect(screen.queryByText("Read-only mode")).not.toBeInTheDocument();

    await waitFor(() =>
      expect(screen.getByLabelText("GA4 vendor credential")).toBeInTheDocument(),
    );
    expect(screen.getByLabelText("GA4 property ID")).toBeInTheDocument();
    expect(screen.getByLabelText("Backfill days")).toBeInTheDocument();
    expect(screen.getByLabelText("Collection hour")).toBeInTheDocument();
    expect(screen.getByLabelText("Collect automatically")).toBeInTheDocument();
  });

  it("lists only ga4 credentials in the picker and shows the service-account email", async () => {
    (vendorCredentials.list as ReturnType<typeof vi.fn>).mockResolvedValue([
      GA4_CREDENTIAL,
      { ...GA4_CREDENTIAL, id: "vc2", name: "app-store-key", provider: "appstore" },
    ]);
    await renderForm();
    selectGa4();

    await waitFor(() =>
      expect(screen.getByRole("option", { name: /analytics-sa/ })).toBeInTheDocument(),
    );
    expect(screen.queryByRole("option", { name: /app-store-key/ })).not.toBeInTheDocument();
    expect(
      screen.getByText(/collector@proj\.iam\.gserviceaccount\.com/),
    ).toBeInTheDocument();
  });

  it("refuses to submit without a credential — toast, invalid select, no create call", async () => {
    await renderForm();
    selectGa4();
    await waitFor(() =>
      expect(screen.getByLabelText("GA4 vendor credential")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByLabelText("Connection name"), {
      target: { value: "GA4 prod" },
    });
    fireEvent.change(screen.getByLabelText("GA4 property ID"), {
      target: { value: "294380179" },
    });

    fireEvent.click(screen.getByText("Create Connection"));

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.stringMatching(/credential/i),
        "error",
      ),
    );
    expect(api.connections.create).not.toHaveBeenCalled();
    expect(screen.getByLabelText("GA4 vendor credential")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("refuses to submit without a property id", async () => {
    await renderForm();
    selectGa4();
    await waitFor(() =>
      expect(screen.getByLabelText("GA4 vendor credential")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByLabelText("Connection name"), {
      target: { value: "GA4 prod" },
    });
    fireEvent.change(screen.getByLabelText("GA4 vendor credential"), {
      target: { value: "vc1" },
    });

    fireEvent.click(screen.getByText("Create Connection"));

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.stringMatching(/property/i),
        "error",
      ),
    );
    expect(api.connections.create).not.toHaveBeenCalled();
  });

  it("posts source_type, the credential and the source_config — and no db host/port/name", async () => {
    (api.connections.create as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "c9",
      project_id: "proj1",
      name: "GA4 prod",
      db_type: "ga4",
      source_type: "ga4",
    });
    await renderForm();
    selectGa4();
    await waitFor(() =>
      expect(screen.getByLabelText("GA4 vendor credential")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByLabelText("Connection name"), {
      target: { value: "GA4 prod" },
    });
    fireEvent.change(screen.getByLabelText("GA4 vendor credential"), {
      target: { value: "vc1" },
    });
    fireEvent.change(screen.getByLabelText("GA4 property ID"), {
      target: { value: "294380179" },
    });
    fireEvent.change(screen.getByLabelText("Collection hour"), {
      target: { value: "5" },
    });

    fireEvent.click(screen.getByText("Create Connection"));

    await waitFor(() => expect(api.connections.create).toHaveBeenCalledTimes(1));
    const payload = (api.connections.create as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(payload).toMatchObject({
      project_id: "proj1",
      name: "GA4 prod",
      source_type: "ga4",
      vendor_credential_id: "vc1",
      collection_enabled: true,
      collection_hour: 5,
      source_config: { property_ids: ["294380179"], backfill_days: 30 },
    });
    expect(payload).not.toHaveProperty("db_host");
    expect(payload).not.toHaveProperty("db_port");
    expect(payload).not.toHaveProperty("db_name");
    expect(payload).not.toHaveProperty("ssh_host");
  });

  it("adds a credential inline without ever echoing the pasted secret back", async () => {
    const secret = JSON.stringify({
      type: "service_account",
      client_email: "new-sa@proj.iam.gserviceaccount.com",
      private_key: "-----BEGIN PRIVATE KEY-----SUPERSECRETVALUE-----END PRIVATE KEY-----",
    });
    (vendorCredentials.list as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (vendorCredentials.create as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "vc-new",
      name: "fresh-sa",
      provider: "ga4",
      fingerprint: "ffff0000ffff0000",
      meta: { client_email: "new-sa@proj.iam.gserviceaccount.com" },
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
    });

    const user = userEvent.setup({ delay: null });
    await renderForm();
    selectGa4();
    await waitFor(() =>
      expect(screen.getByLabelText("GA4 vendor credential")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /new credential/i }));

    fireEvent.change(screen.getByLabelText("Credential name"), {
      target: { value: "fresh-sa" },
    });
    fireEvent.change(screen.getByLabelText("Service account JSON"), {
      target: { value: secret },
    });
    await user.click(screen.getByRole("button", { name: "Add credential" }));

    await waitFor(() => expect(vendorCredentials.create).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.getByRole("option", { name: /fresh-sa/ })).toBeInTheDocument(),
    );
    // The write-only rule: the plaintext is gone from the DOM entirely.
    expect(document.body.textContent).not.toContain("SUPERSECRETVALUE");
    expect(document.body.innerHTML).not.toContain("SUPERSECRETVALUE");
  });

  it("points at the panel that actually exists when no ga4 credential is stored", async () => {
    (vendorCredentials.list as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    await renderForm();
    selectGa4();
    const hint = await screen.findByText(/no google analytics credentials/i);
    // The panel lives in the sidebar's Setup group next to SSH Keys; there is
    // no "Settings → Vendor credentials" to navigate to.
    expect(hint).toHaveTextContent(/setup\s*→\s*vendor credentials/i);
    expect(hint).toHaveTextContent(/sidebar/i);
    expect(hint.textContent ?? "").not.toMatch(/settings\s*→/i);
  });
});

describe("ConnectionSelector — the GA4 row in the list (SCN-113 / SCN-115)", () => {
  function makeGa4Connection(): Connection {
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
      source_config: { property_ids: ["294380179"], backfill_days: 30 },
      collection_enabled: true,
      collection_hour: 3,
    };
  }

  it("badges the source, shows the collection row and hides the DB-only actions", async () => {
    const conn = makeGa4Connection();
    useAppStore.setState({ connections: [conn], activeConnection: conn });

    const { ConnectionSelector } = await import(
      "@/components/connections/ConnectionSelector"
    );
    render(<ConnectionSelector />);

    expect(screen.getByText("GA4")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("collection-outcome")).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Collect now" })).toBeInTheDocument();

    // A GA4 property has no schema to index and no code to cross-reference.
    expect(screen.queryByLabelText("Index database schema")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Run Code-DB Sync")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Refresh schema cache")).not.toBeInTheDocument();
    expect(api.connections.indexDbStatus).not.toHaveBeenCalled();
    expect(api.connections.syncStatus).not.toHaveBeenCalled();
  });

  it("leaves a database connection's affordances alone", async () => {
    const conn: Connection = {
      ...makeGa4Connection(),
      db_type: "postgres",
      source_type: "database",
      db_host: "localhost",
      db_port: 5432,
      db_name: "orders",
      vendor_credential_id: null,
      source_config: null,
    };
    useAppStore.setState({ connections: [conn], activeConnection: conn });

    const { ConnectionSelector } = await import(
      "@/components/connections/ConnectionSelector"
    );
    render(<ConnectionSelector />);

    expect(screen.getByText("postgres")).toBeInTheDocument();
    expect(screen.queryByTestId("collection-outcome")).not.toBeInTheDocument();
    await waitFor(() => expect(api.connections.indexDbStatus).toHaveBeenCalled());
  });
});
