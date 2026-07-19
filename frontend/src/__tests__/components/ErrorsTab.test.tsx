import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { ErrorsTab } from "@/components/logs/ErrorsTab";

const OPEN_ERROR = {
  id: "e1",
  source: "run",
  kind: "db_index",
  failure_kind: "fatal",
  message: "boom",
  occurrences: 3,
  status: "open",
  sample_ref: "r",
  first_seen_at: null,
  last_seen_at: null,
};

const errorsMock = vi.fn();
const updateErrorMock = vi.fn();
const toastMock = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    logs: {
      errors: (...a: unknown[]) => errorsMock(...a),
      updateError: (...a: unknown[]) => updateErrorMock(...a),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: (...a: unknown[]) => toastMock(...a),
}));

beforeEach(() => {
  vi.clearAllMocks();
  errorsMock.mockResolvedValue({ items: [OPEN_ERROR], total: 1, page: 1, page_size: 100 });
  updateErrorMock.mockResolvedValue({ ok: true });
});

describe("ErrorsTab", () => {
  it("lists errors and shows occurrences", async () => {
    render(<ErrorsTab projectId="p" />);
    await waitFor(() => expect(screen.getByText("boom")).toBeTruthy());
    expect(screen.getByText("3")).toBeTruthy();
  });

  it("shows an error state with Retry when the fetch fails (SCN-107)", async () => {
    errorsMock.mockRejectedValueOnce(new Error("server down"));
    render(<ErrorsTab projectId="p" />);
    await waitFor(() => expect(screen.getByText("server down")).toBeTruthy());
    const retry = screen.getByRole("button", { name: "Retry" });
    // Retry re-fetches and, on success, renders the row.
    errorsMock.mockResolvedValueOnce({ items: [OPEN_ERROR], total: 1, page: 1, page_size: 100 });
    fireEvent.click(retry);
    await waitFor(() => expect(screen.getByText("boom")).toBeTruthy());
  });

  it("toasts when cycling a status fails (SCN-107)", async () => {
    updateErrorMock.mockRejectedValueOnce(new Error("nope"));
    render(<ErrorsTab projectId="p" />);
    await waitFor(() => expect(screen.getByText("boom")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Cycle status for e1/ }));
    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith("nope", "error"),
    );
  });
});
