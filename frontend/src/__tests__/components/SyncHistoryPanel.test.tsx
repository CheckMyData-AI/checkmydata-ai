import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { SyncHistoryPanel } from "@/components/knowledge/SyncHistoryPanel";

vi.mock("@/lib/api", () => ({
  api: {
    projects: {
      syncHistory: vi.fn(async () => ({
        runs: [
          {
            id: "r1",
            trigger: "scheduled",
            status: "success",
            duration_seconds: 12,
            error_message: null,
            created_at: new Date().toISOString(),
            steps: null,
          },
        ],
      })),
    },
  },
}));

describe("SyncHistoryPanel", () => {
  it("renders the latest run status", async () => {
    render(<SyncHistoryPanel projectId="p1" />);
    await waitFor(() =>
      expect(screen.getAllByText(/success/i).length).toBeGreaterThan(0),
    );
  });

  it("shows empty state when there are no runs", async () => {
    const { api } = await import("@/lib/api");
    (api.projects.syncHistory as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      runs: [],
    });
    render(<SyncHistoryPanel projectId="p1" />);
    await waitFor(() =>
      expect(screen.getByText(/No scheduled syncs yet/i)).toBeInTheDocument(),
    );
  });
});
