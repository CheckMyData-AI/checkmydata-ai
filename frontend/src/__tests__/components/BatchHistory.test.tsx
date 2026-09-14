/**
 * Past batch runs existed in the database and nowhere in the interface.
 *
 * `GET /api/batch?project_id=` and `DELETE /api/batch/{id}` have had typed clients
 * since they shipped and no component caller, so a user opened the runner, executed,
 * read the results in the modal, and closing it was final.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const list = vi.fn();
const del = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/lib/api", () => ({ api: { batch: { list, delete: del } } }));

const pushToast = vi.fn();
vi.mock("@/stores/toast-store", () => ({
  toast: (...a: unknown[]) => pushToast(...a),
  useToastStore: Object.assign((sel?: (s: unknown) => unknown) => (sel ? sel({}) : {}), {
    setState: vi.fn(),
    getState: () => ({}),
  }),
}));

const run = (over = {}) => ({
  id: "b1",
  user_id: "u1",
  project_id: "p1",
  connection_id: "c1",
  title: "Monthly revenue",
  queries_json: '[{"sql":"SELECT 1","title":"a"},{"sql":"SELECT 2","title":"b"}]',
  note_ids_json: null,
  status: "completed",
  results_json: "[]",
  created_at: "2026-09-01T10:00:00Z",
  completed_at: "2026-09-01T10:02:00Z",
  ...over,
});

beforeEach(() => vi.clearAllMocks());

describe("BatchHistory", () => {
  it("lists past runs with their query count and status", async () => {
    list.mockResolvedValueOnce([run()]);
    const { BatchHistory } = await import("@/components/batch/BatchHistory");
    render(<BatchHistory projectId="p1" />);

    await waitFor(() => expect(screen.getByText("Monthly revenue")).toBeTruthy());
    expect(screen.getByText(/2 queries · completed/)).toBeTruthy();
  });

  it("says there are none rather than rendering an empty box", async () => {
    list.mockResolvedValueOnce([]);
    const { BatchHistory } = await import("@/components/batch/BatchHistory");
    render(<BatchHistory projectId="p1" />);
    await waitFor(() => expect(screen.getByText(/No batch runs yet/i)).toBeTruthy());
  });

  it("offers a retry when the list cannot be loaded, rather than an empty list", async () => {
    list.mockRejectedValueOnce(new Error("network down"));
    const { BatchHistory } = await import("@/components/batch/BatchHistory");
    render(<BatchHistory projectId="p1" />);
    await waitFor(() => expect(screen.getByText("network down")).toBeTruthy());
  });

  it("removes a run from the list when the delete succeeds", async () => {
    list.mockResolvedValueOnce([run(), run({ id: "b2", title: "Churn" })]);
    const { BatchHistory } = await import("@/components/batch/BatchHistory");
    render(<BatchHistory projectId="p1" />);
    await waitFor(() => expect(screen.getByText("Churn")).toBeTruthy());

    await userEvent.click(screen.getByLabelText("Delete Churn"));
    await waitFor(() => expect(screen.queryByText("Churn")).toBeNull());
    expect(screen.getByText("Monthly revenue")).toBeTruthy();
  });

  it("keeps the row and says so when the delete fails", async () => {
    list.mockResolvedValueOnce([run()]);
    del.mockRejectedValueOnce(new Error("not yours"));
    const { BatchHistory } = await import("@/components/batch/BatchHistory");
    render(<BatchHistory projectId="p1" />);
    await waitFor(() => expect(screen.getByText("Monthly revenue")).toBeTruthy());

    await userEvent.click(screen.getByLabelText("Delete Monthly revenue"));
    await waitFor(() => expect(pushToast).toHaveBeenCalledWith("not yours", "error"));
    expect(screen.getByText("Monthly revenue")).toBeTruthy();
  });
});
