import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ErrorsTab } from "@/components/logs/ErrorsTab";

const errorsMock = vi.fn().mockResolvedValue({
  items: [
    {
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
    },
  ],
  total: 1,
  page: 1,
  page_size: 100,
});

vi.mock("@/lib/api", () => ({
  api: {
    logs: {
      errors: (...a: unknown[]) => errorsMock(...a),
      updateError: vi.fn().mockResolvedValue({ ok: true }),
    },
  },
}));

describe("ErrorsTab", () => {
  it("lists errors and shows occurrences", async () => {
    render(<ErrorsTab projectId="p" />);
    await waitFor(() => expect(screen.getByText("boom")).toBeTruthy());
    expect(screen.getByText("3")).toBeTruthy();
  });
});
