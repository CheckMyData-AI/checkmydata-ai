import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { BatchQueryDTO } from "@/lib/api";

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

vi.mock("@/components/ui/Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

vi.mock("@/components/ui/Tooltip", () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/hooks/useDialogA11y", () => ({
  useDialogA11y: vi.fn(),
}));

vi.mock("@/components/viz/DataTable", () => ({
  DataTable: ({ data }: { data: { columns?: string[]; total_rows?: number } }) => (
    <div data-testid="data-table" data-total={String(data.total_rows)}>
      {(data.columns ?? []).join(",")}
    </div>
  ),
}));

vi.mock("@/lib/api", () => ({
  api: {
    batch: {
      get: vi.fn(),
      export: vi.fn(),
    },
  },
}));

const { api } = await import("@/lib/api");
const { BatchResults } = await import("@/components/batch/BatchResults");

function makeBatch(overrides: Partial<BatchQueryDTO> = {}): BatchQueryDTO {
  return {
    id: "b1",
    user_id: "u1",
    project_id: "p1",
    connection_id: "c1",
    title: "My Batch",
    queries_json: "[]",
    note_ids_json: null,
    status: "completed",
    results_json: null,
    created_at: null,
    completed_at: null,
    ...overrides,
  };
}

const successEntry = {
  title: "Users",
  sql: "SELECT id, name FROM users",
  status: "success",
  columns: ["id", "name"],
  rows: [
    [1, "alice"],
    [2, "bob"],
  ],
  total_rows: 2,
  duration_ms: 12,
};

const failedEntry = {
  title: "Broken",
  sql: "SELECT bad",
  status: "failed",
  error: "column bad does not exist",
  duration_ms: 3,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("BatchResults", () => {
  it("shows a loading spinner while fetching", async () => {
    let resolve!: (v: BatchQueryDTO) => void;
    vi.mocked(api.batch.get).mockReturnValue(
      new Promise<BatchQueryDTO>((r) => {
        resolve = r;
      }),
    );

    const { container } = render(<BatchResults batchId="b1" />);
    await waitFor(() => {
      expect(container.querySelector(".animate-spin")).toBeInTheDocument();
    });

    resolve(makeBatch({ results_json: "[]" }));
    await waitFor(() => {
      expect(container.querySelector(".animate-spin")).not.toBeInTheDocument();
    });
  });

  it("renders a success table and a failed error block after load", async () => {
    vi.mocked(api.batch.get).mockResolvedValue(
      makeBatch({
        status: "partially_failed",
        results_json: JSON.stringify([successEntry, failedEntry]),
      }),
    );

    render(<BatchResults batchId="b1" />);

    await waitFor(() => {
      expect(screen.getByTestId("data-table")).toBeInTheDocument();
    });
    // Success block: title + column-keyed table (columns forwarded to DataTable).
    expect(screen.getByText("Users")).toBeInTheDocument();
    expect(screen.getByText("id,name")).toBeInTheDocument();
    expect(screen.getByTestId("data-table").getAttribute("data-total")).toBe("2");
    // Failed block: title + honest error text.
    expect(screen.getByText("Broken")).toBeInTheDocument();
    expect(screen.getByText("column bad does not exist")).toBeInTheDocument();
  });

  it("shows an empty 'still running' state when there are no results yet", async () => {
    vi.mocked(api.batch.get).mockResolvedValue(
      makeBatch({ status: "running", results_json: null }),
    );

    render(<BatchResults batchId="b1" />);

    await waitFor(() => {
      expect(screen.getByText(/still running/i)).toBeInTheDocument();
    });
    expect(screen.queryByTestId("data-table")).not.toBeInTheDocument();
  });

  it("shows an error state with Retry when the fetch fails, then recovers", async () => {
    vi.mocked(api.batch.get).mockRejectedValueOnce(new Error("network"));

    render(<BatchResults batchId="b1" />);

    await waitFor(() => {
      expect(screen.getByText("Couldn't load batch results")).toBeInTheDocument();
    });
    const retry = screen.getByText("Retry");
    expect(retry).toBeInTheDocument();

    vi.mocked(api.batch.get).mockResolvedValue(
      makeBatch({ results_json: JSON.stringify([successEntry]) }),
    );
    await userEvent.click(retry);

    await waitFor(() => {
      expect(screen.getByTestId("data-table")).toBeInTheDocument();
    });
  });

  it("wires onBack and onClose into visible controls", async () => {
    vi.mocked(api.batch.get).mockResolvedValue(makeBatch({ results_json: "[]" }));
    const onBack = vi.fn();
    const onClose = vi.fn();

    render(<BatchResults batchId="b1" onBack={onBack} onClose={onClose} />);
    await waitFor(() => {
      expect(screen.getByLabelText("Back to runner")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByLabelText("Back to runner"));
    expect(onBack).toHaveBeenCalled();
    await userEvent.click(screen.getByLabelText("Close batch results"));
    expect(onClose).toHaveBeenCalled();
  });

  it("exports the batch as a downloadable blob", async () => {
    vi.mocked(api.batch.get).mockResolvedValue(
      makeBatch({ results_json: JSON.stringify([successEntry]) }),
    );
    const blob = new Blob(["x"], { type: "application/octet-stream" });
    vi.mocked(api.batch.export).mockResolvedValue(blob);

    const createObjectURL = vi.fn(() => "blob:mock");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    render(<BatchResults batchId="b1" />);
    await waitFor(() => {
      expect(screen.getByTestId("data-table")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByText("Export"));
    await waitFor(() => {
      expect(api.batch.export).toHaveBeenCalledWith("b1");
    });
    expect(clickSpy).toHaveBeenCalled();
    clickSpy.mockRestore();
  });
});
