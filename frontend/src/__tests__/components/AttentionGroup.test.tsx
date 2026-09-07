import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useAppStore } from "@/stores/app-store";
import { AttentionGroup } from "@/components/attention/AttentionGroup";

const attention = vi.fn();
const setPanel = vi.fn();

vi.mock("@/lib/api", () => ({
  api: { projects: { attention: (...a: unknown[]) => attention(...a) } },
}));

vi.mock("@/hooks/useAppPanel", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useAppPanel")>(
    "@/hooks/useAppPanel",
  );
  return { ...actual, useAppPanel: () => ({ panel: null, setPanel }) };
});

vi.mock("@/components/ui/Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

const PROJECT = {
  id: "p1",
  name: "esim-php",
  description: "",
  repo_url: null,
  repo_branch: "main",
  ssh_key_id: null,
  created_at: "",
  updated_at: "",
};

beforeEach(() => {
  attention.mockReset();
  setPanel.mockReset();
  useAppStore.setState({ activeProject: PROJECT as never });
});

describe("AttentionGroup", () => {
  it("renders NOTHING when nothing needs the user", async () => {
    // Absent, not empty. A permanent "all good" box is one people stop reading, and
    // the whole value of this group is that its presence means something.
    attention.mockResolvedValue({ items: [], more: 0, degraded: [] });
    const { container } = render(<AttentionGroup />);
    await waitFor(() => expect(attention).toHaveBeenCalled());
    expect(container.querySelector("[data-testid='attention-group']")).toBeNull();
  });

  it("says it could not check, which is not the same as nothing to report", async () => {
    attention.mockResolvedValue({ items: [], more: 0, degraded: ["runs"] });
    render(<AttentionGroup />);
    expect(await screen.findByText(/could not check runs/i)).toBeInTheDocument();
  });

  it("treats its own request failing the same way", async () => {
    attention.mockRejectedValue(new Error("offline"));
    render(<AttentionGroup />);
    expect(await screen.findByText(/could not check/i)).toBeInTheDocument();
  });

  it("shows what happened and to what", async () => {
    attention.mockResolvedValue({
      items: [
        {
          kind: "index_failed",
          subject: "index repo",
          what: "reaped as stale at graph_build — it may not have been dead",
          severity: "critical",
          route: "panel=logs",
          at: null,
        },
      ],
      more: 0,
      degraded: [],
    });
    render(<AttentionGroup />);
    expect(await screen.findByText("index repo")).toBeInTheDocument();
    expect(screen.getByText(/reaped as stale at graph_build/)).toBeInTheDocument();
  });

  it("routes an entry to the panel that fixes it", async () => {
    // An item a user can read but not act on is a complaint, not a notification.
    attention.mockResolvedValue({
      items: [
        {
          kind: "connection_never_indexed",
          subject: "prod",
          what: "never indexed",
          severity: "warning",
          route: "panel=connections",
          at: null,
        },
      ],
      more: 0,
      degraded: [],
    });
    render(<AttentionGroup />);
    await userEvent.click(await screen.findByText("prod"));
    expect(setPanel).toHaveBeenCalledWith("connections");
  });

  it("says how many it did not show", async () => {
    // A silent truncation reads as "that is everything".
    attention.mockResolvedValue({
      items: [
        {
          kind: "connection_never_indexed",
          subject: "a",
          what: "never indexed",
          severity: "warning",
          route: "panel=connections",
          at: null,
        },
      ],
      more: 4,
      degraded: [],
    });
    render(<AttentionGroup />);
    expect(await screen.findByText(/4 more/)).toBeInTheDocument();
  });

  it("asks nothing when there is no project", async () => {
    useAppStore.setState({ activeProject: null });
    render(<AttentionGroup />);
    await waitFor(() => expect(attention).not.toHaveBeenCalled());
  });
});
