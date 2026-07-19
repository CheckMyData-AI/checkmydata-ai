import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { KnowledgeHub } from "@/components/knowledge/KnowledgeHub";

const getCatalogMock = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    semanticLayer: {
      getCatalog: (...a: unknown[]) => getCatalogMock(...a),
    },
  },
}));

vi.mock("@/stores/app-store", () => {
  // Stable references so the effect's deps don't change on every render.
  const activeProject = { id: "p1" };
  const activeConnection = { id: "c1" };
  return {
    useAppStore: (
      selector: (s: {
        activeProject: { id: string } | null;
        activeConnection: { id: string } | null;
      }) => unknown,
    ) => selector({ activeProject, activeConnection }),
  };
});

vi.mock("@/components/knowledge/KnowledgeDocs", () => ({
  KnowledgeDocs: () => <div data-testid="docs" />,
}));

vi.mock("@/components/insights/InsightFeedPanel", () => ({
  InsightFeedPanel: () => <div data-testid="insights" />,
}));

beforeEach(() => {
  vi.clearAllMocks();
  getCatalogMock.mockResolvedValue({ metrics: [] });
});

describe("KnowledgeHub metrics tab", () => {
  it("surfaces an error + Retry (not an empty state) when the catalog fetch fails (SCN-067)", async () => {
    getCatalogMock.mockRejectedValueOnce(new Error("catalog down"));
    render(<KnowledgeHub />);

    fireEvent.click(screen.getByRole("button", { name: "Metrics" }));

    await waitFor(() => expect(screen.getByText("catalog down")).toBeTruthy());
    // The misleading "No metrics found" empty state must NOT be what the user sees.
    expect(screen.queryByText("No metrics found")).toBeNull();

    // Retry re-fetches; on success the error clears to the real (empty) state.
    getCatalogMock.mockResolvedValueOnce({ metrics: [] });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.getByText("No metrics found")).toBeTruthy());
    expect(screen.queryByText("catalog down")).toBeNull();
    expect(getCatalogMock).toHaveBeenCalledTimes(2);
  });
});
