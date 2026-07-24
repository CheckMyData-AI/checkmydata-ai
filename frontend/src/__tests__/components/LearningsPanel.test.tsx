import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const listLearnings = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    connections: {
      listLearnings: (...a: unknown[]) => listLearnings(...a),
      deleteLearning: vi.fn(),
      updateLearning: vi.fn(),
      recompileLearnings: vi.fn(),
      confirmLearning: vi.fn(),
      contradictLearning: vi.fn(),
      clearLearnings: vi.fn(),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

vi.mock("@/hooks/usePermission", () => ({
  usePermission: () => ({ canDelete: true, canEdit: true }),
}));

vi.mock("@/components/ui/ConfirmModal", () => ({
  confirmAction: vi.fn().mockResolvedValue(true),
}));

import { LearningsPanel } from "@/components/learnings/LearningsPanel";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("LearningsPanel load failure (M5)", () => {
  it("shows inline error with Retry instead of the empty state", async () => {
    listLearnings.mockRejectedValueOnce(new Error("network down"));
    render(<LearningsPanel connectionId="c1" onClose={() => {}} />);

    expect(
      await screen.findByText("Failed to load learnings"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/No learnings yet/),
    ).not.toBeInTheDocument();

    listLearnings.mockResolvedValueOnce([
      {
        id: "l1",
        connection_id: "c1",
        category: "query_pattern",
        subject: "orders",
        lesson: "Prefer index on created_at",
        confidence: 0.9,
        times_confirmed: 2,
        times_contradicted: 0,
        times_applied: 5,
        is_active: true,
        created_at: "2026-07-01T00:00:00Z",
        updated_at: "2026-07-02T00:00:00Z",
      },
    ]);

    const user = userEvent.setup({ delay: null });
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => {
      expect(screen.getByText(/Prefer index on created_at/)).toBeInTheDocument();
    });
    expect(screen.queryByText("Failed to load learnings")).not.toBeInTheDocument();
  });

  it("keeps the real empty state when the load succeeds with no rows", async () => {
    listLearnings.mockResolvedValueOnce([]);
    render(<LearningsPanel connectionId="c1" onClose={() => {}} />);

    expect(await screen.findByText(/No learnings yet/)).toBeInTheDocument();
    expect(screen.queryByText("Failed to load learnings")).not.toBeInTheDocument();
  });
});
