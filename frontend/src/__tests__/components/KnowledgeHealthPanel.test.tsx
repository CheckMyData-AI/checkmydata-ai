import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const knowledgeHealthMock = vi.fn();
const indexDbMock = vi
  .fn()
  .mockResolvedValue({ status: "started", run_id: "r9", workflow_id: "w9", connection_id: "c1" });
const triggerSyncMock = vi
  .fn()
  .mockResolvedValue({ status: "started", run_id: "rs", workflow_id: "ws", connection_id: "c1" });
const repoIndexMock = vi
  .fn()
  .mockResolvedValue({ status: "started", run_id: "rr", workflow_id: "w1" });
const pipelineStatusMock = vi.fn().mockResolvedValue({
  project_id: "p1",
  any_running: true,
  repo: { is_indexing: false, last_indexed_at: null, last_indexed_commit: null },
  connections: [],
});

vi.mock("@/lib/api", () => ({
  api: {
    projects: {
      knowledgeHealth: (...args: unknown[]) => knowledgeHealthMock(...args),
      pipelineStatus: (...args: unknown[]) => pipelineStatusMock(...args),
    },
    connections: {
      indexDb: (...args: unknown[]) => indexDbMock(...args),
      triggerSync: (...args: unknown[]) => triggerSyncMock(...args),
    },
    repos: { index: (...args: unknown[]) => repoIndexMock(...args) },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

function makeHealth(overrides: Record<string, unknown> = {}) {
  return {
    project_id: "p1",
    connection_id: "c1",
    freshness: {
      overall_stale: false,
      db_index_age_hours: 2,
      db_index_stale: false,
      sync_status: "completed",
      sync_stale: false,
      git_behind_commits: null,
      git_unindexed: false,
      code_graph_symbol_count: 100,
      code_graph_stale: false,
      warnings: [],
    },
    artifact_counts: { tables: 3, learnings: 1, insights: 0, rules: 2, lineage: 1 },
    ...overrides,
  };
}

async function renderPanel(health: Record<string, unknown> = {}) {
  knowledgeHealthMock.mockResolvedValue(makeHealth(health));
  const { KnowledgeHealthPanel } = await import(
    "@/components/knowledge/KnowledgeHealthPanel"
  );
  return render(<KnowledgeHealthPanel projectId="p1" connectionId="c1" />);
}

describe("KnowledgeHealthPanel", () => {
  it("renders artifact counts", async () => {
    await renderPanel();
    await waitFor(() => {
      expect(screen.getByText("Tables")).toBeInTheDocument();
      expect(screen.getByText("Lineage")).toBeInTheDocument();
    });
  });

  it("shows the fresh state when nothing is stale", async () => {
    await renderPanel();
    await waitFor(() => {
      expect(screen.getByText(/Everything is fresh/)).toBeInTheDocument();
    });
  });

  it("renders an actionable warning and triggers re-index", async () => {
    await renderPanel({
      freshness: {
        overall_stale: true,
        db_index_age_hours: 72,
        db_index_stale: true,
        sync_status: "completed",
        sync_stale: false,
        git_behind_commits: null,
        git_unindexed: false,
        code_graph_symbol_count: 100,
        code_graph_stale: false,
        warnings: [
          {
            category: "db_index",
            severity: "warning",
            message: "Database index is 72h old; consider re-indexing.",
            recommended_action: {
              kind: "reindex_db",
              label: "Re-index database",
              connection_id: "c1",
            },
          },
        ],
      },
    });

    const { useBackgroundTasks } = await import("@/stores/background-tasks-store");
    const insertSpy = vi.spyOn(useBackgroundTasks.getState(), "insertOptimistic");

    const btn = await screen.findByRole("button", { name: "Re-index database" });
    await userEvent.click(btn);

    await waitFor(() => {
      expect(indexDbMock).toHaveBeenCalledWith("c1");
    });
    expect(insertSpy).toHaveBeenCalledWith(expect.objectContaining({ runId: "r9" }));
  });

  it("shows an error state when the request fails", async () => {
    knowledgeHealthMock.mockRejectedValue(new Error("boom"));
    const { KnowledgeHealthPanel } = await import(
      "@/components/knowledge/KnowledgeHealthPanel"
    );
    render(<KnowledgeHealthPanel projectId="p1" connectionId="c1" />);
    await waitFor(() => {
      expect(screen.getByText(/Could not load knowledge health/)).toBeInTheDocument();
    });
  });
});
