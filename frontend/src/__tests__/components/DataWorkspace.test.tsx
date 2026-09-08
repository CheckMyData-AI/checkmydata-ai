import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { useAppStore } from "@/stores/app-store";
import { DataWorkspace } from "@/components/workspace/DataWorkspace";

/**
 * `SCR-01`. Three claims the screen makes that are worth holding:
 *
 * - the ordering is **stated**, not discovered (`SCN-131`) — a repository connected
 *   before any data source is never picked up by the nightly wave, and nothing used to
 *   say so;
 * - a card says what the agent can DO with the source (`SCN-132`), read from the API
 *   rather than re-derived here;
 * - the sync hour says why it cannot be changed (`SCN-147`), where the automation would
 *   have been rather than on a billing page nobody opens.
 */

const docs = vi.fn();
const syncSchedule = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    repos: { docs: (...a: unknown[]) => docs(...a) },
    projects: {
      syncSchedule: (...a: unknown[]) => syncSchedule(...a),
      setSyncSchedule: vi.fn(),
    },
    connections: { update: vi.fn() },
  },
}));

vi.mock("@/hooks/useAppPanel", () => ({
  useAppPanel: () => ({ panel: null, setPanel: vi.fn() }),
}));
vi.mock("@/hooks/usePermission", () => ({ usePermission: () => ({ canEdit: true }) }));
vi.mock("@/stores/toast-store", () => ({ toast: vi.fn() }));
vi.mock("@/components/ui/Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));
vi.mock("@/components/connections/ConnectionSelector", () => ({
  ConnectionSelector: () => <div data-testid="connection-selector" />,
}));
vi.mock("@/components/connections/SyncStatusIndicator", () => ({
  SyncStatusIndicator: () => <div data-testid="sync-status" />,
}));

const PROJECT = {
  id: "p1",
  name: "esim-php",
  description: "",
  repo_url: "git@github.com:t/r.git",
  repo_branch: "main",
  ssh_key_id: null,
  created_at: "",
  updated_at: "",
};

function conn(over: Record<string, unknown> = {}) {
  return {
    id: "c1",
    project_id: "p1",
    name: "nicegram",
    db_type: "postgres",
    source_type: "database",
    is_read_only: true,
    is_active: true,
    capability: "queryable",
    purpose: null,
    ...over,
  };
}

beforeEach(() => {
  docs.mockReset().mockResolvedValue([]);
  syncSchedule
    .mockReset()
    .mockResolvedValue({ enabled: true, hour: 3, timezone: "UTC", next_run: null, may_run: true });
  useAppStore.setState({ activeProject: PROJECT as never, connections: [] as never });
});

describe("DataWorkspace", () => {
  it("states the ordering when nothing is connected", async () => {
    render(<DataWorkspace />);
    expect(
      await screen.findByText(/a data source comes first/i),
    ).toBeInTheDocument();
  });

  it("says what the agent can do with a source", async () => {
    useAppStore.setState({ connections: [conn()] as never });
    render(<DataWorkspace />);
    expect(await screen.findByText(/the agent can query this/i)).toBeInTheDocument();
    expect(screen.getByText("read-only")).toBeInTheDocument();
  });

  it("never advertises an analytics source as queryable", async () => {
    // The failure this guards: `db_type` carries the VENDOR id for an analytics
    // source, so a card that read it naively would offer to query GA4 — and the
    // connector raises the moment the model takes the offer.
    useAppStore.setState({
      connections: [conn({ db_type: "ga4", source_type: "ga4", capability: "collected" })] as never,
    });
    render(<DataWorkspace />);
    expect(await screen.findByText(/collected on a schedule/i)).toBeInTheDocument();
    expect(screen.queryByText(/can query this/i)).toBeNull();
  });

  it("says the agent is inferring when nothing is described", async () => {
    useAppStore.setState({ connections: [conn()] as never });
    render(<DataWorkspace />);
    expect(await screen.findByText(/no purpose set/i)).toBeInTheDocument();
  });

  it("shows the description once there is one", async () => {
    useAppStore.setState({
      connections: [conn({ purpose: "Money is in minor units.\nSecond line." })] as never,
    });
    render(<DataWorkspace />);
    expect(await screen.findByText("Money is in minor units.")).toBeInTheDocument();
    // First line only — the card is a summary, not the whole note.
    expect(screen.queryByText("Second line.")).toBeNull();
  });

  it("disables the sync hour and says why when the account may not run it", async () => {
    syncSchedule.mockResolvedValue({
      enabled: true,
      hour: 3,
      timezone: "UTC",
      next_run: null,
      may_run: false,
    });
    render(<DataWorkspace />);
    const select = await screen.findByLabelText("Nightly sync hour");
    expect(select).toBeDisabled();
    expect(screen.getByText(/scheduled syncs need a subscription/i)).toBeInTheDocument();
  });

  it("leaves the sync hour editable when it can run", async () => {
    render(<DataWorkspace />);
    expect(await screen.findByLabelText("Nightly sync hour")).not.toBeDisabled();
  });

  it("says it could not check rather than showing a working control", async () => {
    // Unknown is not "enabled". Rendering it as editable promises a nightly run
    // nobody has checked can happen.
    syncSchedule.mockRejectedValue(new Error("offline"));
    render(<DataWorkspace />);
    expect(await screen.findByText(/could not check the sync schedule/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Nightly sync hour")).toBeNull();
  });

  it("tells a repository owner when nothing will pick it up", async () => {
    useAppStore.setState({ connections: [] as never });
    render(<DataWorkspace />);
    expect(await screen.findByText(/indexed manually only/i)).toBeInTheDocument();
  });

  it("asks for a project before rendering anything", async () => {
    useAppStore.setState({ activeProject: null });
    render(<DataWorkspace />);
    expect(screen.getByText(/select a project first/i)).toBeInTheDocument();
    await waitFor(() => expect(docs).not.toHaveBeenCalled());
  });
});
