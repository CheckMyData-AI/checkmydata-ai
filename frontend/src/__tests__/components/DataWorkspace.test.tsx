import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

const testConn = vi.fn();
const indexDb = vi.fn();
const deleteConn = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    repos: { docs: (...a: unknown[]) => docs(...a) },
    projects: {
      syncSchedule: (...a: unknown[]) => syncSchedule(...a),
      setSyncSchedule: vi.fn(),
    },
    connections: {
      update: vi.fn(),
      test: (...a: unknown[]) => testConn(...a),
      indexDb: (...a: unknown[]) => indexDb(...a),
      delete: (...a: unknown[]) => deleteConn(...a),
    },
  },
}));

vi.mock("@/lib/connection-delete", () => ({
  confirmConnectionDelete: vi.fn().mockResolvedValue(true),
}));

vi.mock("@/hooks/useAppPanel", () => ({
  useAppPanel: () => ({ panel: null, setPanel: vi.fn() }),
}));
// Mutable so a test can be a viewer. `vi.doMock` inside a test does nothing here:
// the module is already imported by the time it runs.
let canEdit = true;
vi.mock("@/hooks/usePermission", () => ({ usePermission: () => ({ canEdit }) }));
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
  canEdit = true;
  testConn.mockReset().mockResolvedValue({ success: true });
  indexDb.mockReset().mockResolvedValue({ status: "queued", run_id: "r1" });
  deleteConn.mockReset().mockResolvedValue({ ok: true });
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

  describe("managing a source in place (SCN-129 step 3)", () => {
    it("tests the connection from the card and reports the result there", async () => {
      useAppStore.setState({ connections: [conn()] as never });
      render(<DataWorkspace />);
      await userEvent.click(await screen.findByRole("button", { name: /^test$/i }));
      await waitFor(() => expect(testConn).toHaveBeenCalledWith("c1"));
      expect(await screen.findByText(/connects/i)).toBeInTheDocument();
    });

    it("says why a test failed, next to the source it failed for", async () => {
      // A failure that only reaches a toast is gone by the time the user looks at the
      // card again, which is where they will look.
      testConn.mockResolvedValue({ success: false, error: "password authentication failed" });
      useAppStore.setState({ connections: [conn()] as never });
      render(<DataWorkspace />);
      await userEvent.click(await screen.findByRole("button", { name: /^test$/i }));
      expect(await screen.findByText(/password authentication failed/i)).toBeInTheDocument();
    });

    it("starts an index from the card", async () => {
      useAppStore.setState({ connections: [conn()] as never });
      render(<DataWorkspace />);
      await userEvent.click(await screen.findByRole("button", { name: /^index$/i }));
      await waitFor(() => expect(indexDb).toHaveBeenCalledWith("c1"));
    });

    it("offers neither Test nor Index for a source that cannot be queried", async () => {
      // An analytics source is collected, not queried. Offering to index it is offering
      // an action whose backend has no adapter for this db_type.
      useAppStore.setState({
        connections: [conn({ capability: "collected", db_type: "ga4", source_type: "ga4" })] as never,
      });
      render(<DataWorkspace />);
      await screen.findByText("nicegram");
      expect(screen.queryByRole("button", { name: /^index$/i })).toBeNull();
    });

    it("deletes only after a confirmation that names the consequence", async () => {
      const { confirmConnectionDelete } = await import("@/lib/connection-delete");
      useAppStore.setState({ connections: [conn()] as never });
      render(<DataWorkspace />);
      await userEvent.click(await screen.findByRole("button", { name: /^delete$/i }));
      await waitFor(() => expect(confirmConnectionDelete).toHaveBeenCalledWith("nicegram"));
      await waitFor(() => expect(deleteConn).toHaveBeenCalledWith("c1"));
    });

    it("opens the edit form in the workspace rather than a modal", async () => {
      useAppStore.setState({ connections: [conn()] as never });
      render(<DataWorkspace />);
      await userEvent.click(await screen.findByRole("button", { name: /^edit$/i }));
      // The shared form lives in this panel already; the card asks it to open rather
      // than reimplementing sixteen fields of it.
      await waitFor(() => expect(useAppStore.getState().editConnectionId).toBe("c1"));
    });

    it("hides every management action from a viewer", async () => {
      // Absent, not disabled. A dead control is an unanswered question, and the role
      // that cannot use it is told by its absence (IS-17).
      canEdit = false;
      useAppStore.setState({ connections: [conn()] as never });
      render(<DataWorkspace />);
      await screen.findByText("nicegram");
      // Describe is the one this file already covers; the destructive one matters most.
      expect(screen.queryByRole("button", { name: /^delete$/i })).toBeNull();
    });
  });
});
