/**
 * SCN-115 — the collection row on a GA4 connection.
 *
 * The honesty requirements live here: `ok` / `partial` / `failed` must read
 * differently, a period that was collected as zero must not look like a period
 * that was never collected, and a truncation/degradation caveat on an otherwise
 * successful run must render as a caveat — not as an error.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  CollectionReportStatus,
  CollectionStatus,
} from "@/lib/api/connections";

vi.mock("@/lib/api", () => ({
  api: {
    connections: {
      health: vi.fn().mockResolvedValue({ status: "healthy", latency_ms: 5 }),
      reconnect: vi.fn(),
      collectionStatus: vi.fn(),
      collectNow: vi.fn(),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({ toast: vi.fn() }));

vi.mock("@/lib/sse", () => ({ onEvent: () => () => {} }));

vi.mock("@/components/ui/Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

vi.mock("@/components/ui/Tooltip", () => ({
  Tooltip: ({ children, label }: { children: React.ReactNode; label: string }) => (
    <div title={label}>{children}</div>
  ),
}));

const { api } = await import("@/lib/api");
const { toast } = await import("@/stores/toast-store");

function status(overrides: Partial<CollectionStatus> = {}): CollectionStatus {
  return {
    connection_id: "c1",
    source_type: "ga4",
    status: "ok",
    last_run_at: new Date().toISOString(),
    next_scheduled_hour: 3,
    collection_enabled: true,
    collection_hour: 3,
    timezone: "UTC",
    backfill_days: 30,
    pending_periods: 0,
    reports: [],
    ...overrides,
  };
}

function report(
  overrides: Partial<CollectionReportStatus> = {},
): CollectionReportStatus {
  return {
    report: "overview",
    grain: "daily",
    latest_ok_period: "2026-07-31",
    latest_collected_period: "2026-07-31",
    ok_periods: 30,
    empty_periods: 0,
    failed_periods: 0,
    rows_written: 300,
    pending_periods: 0,
    pending_sample: [],
    last_run_at: new Date().toISOString(),
    last_error: null,
    caveat: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.connections.collectionStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
    status(),
  );
  (api.connections.collectNow as ReturnType<typeof vi.fn>).mockResolvedValue({
    status: "queued",
  });
});

async function renderRow() {
  const { CollectionStatusRow } = await import(
    "@/components/connections/ConnectionHealth"
  );
  return render(<CollectionStatusRow connectionId="c1" />);
}

describe("CollectionStatusRow — outcome badge (SCN-115)", () => {
  it("renders ok, partial and failed distinctly", async () => {
    (api.connections.collectionStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      status({ status: "ok" }),
    );
    const okView = await renderRow();
    const okBadge = await screen.findByTestId("collection-outcome");
    expect(okBadge).toHaveTextContent(/ok/i);
    const okClass = okBadge.className;
    okView.unmount();

    (api.connections.collectionStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      status({ status: "partial" }),
    );
    const partialView = await renderRow();
    const partialBadge = await screen.findByTestId("collection-outcome");
    expect(partialBadge).toHaveTextContent(/partial/i);
    const partialClass = partialBadge.className;
    partialView.unmount();

    (api.connections.collectionStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      status({ status: "failed" }),
    );
    await renderRow();
    const failedBadge = await screen.findByTestId("collection-outcome");
    expect(failedBadge).toHaveTextContent(/failed/i);

    expect(new Set([okClass, partialClass, failedBadge.className]).size).toBe(3);
  });

  it("explains the badge to a keyboard and a screen reader, not just a mouse", async () => {
    (api.connections.collectionStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      status({ status: "partial" }),
    );
    await renderRow();
    const badge = await screen.findByTestId("collection-outcome");

    // The tooltip is the only place the badge's meaning is written down, and
    // Tooltip opens on focus — so the badge has to be focusable to reach it.
    expect(badge).toHaveAttribute("tabindex", "0");
    // …and the meaning is on the element itself for anyone not seeing a popup.
    expect(badge).toHaveAccessibleName(/collection status: partial/i);
    expect(badge).toHaveAccessibleName(/still owed/i);
  });

  it("distinguishes 'never collected' from a collected-zero run", async () => {
    (api.connections.collectionStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      status({
        status: "never_collected",
        last_run_at: null,
        pending_periods: 30,
        reports: [
          report({
            latest_ok_period: null,
            latest_collected_period: null,
            ok_periods: 0,
            rows_written: 0,
            pending_periods: 30,
            pending_sample: ["2026-07-01", "2026-07-02"],
            last_run_at: null,
          }),
        ],
      }),
    );
    const view = await renderRow();
    expect(await screen.findByTestId("collection-outcome")).toHaveTextContent(
      /not collected/i,
    );
    expect(screen.getByText(/not collected yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/no rows/i)).not.toBeInTheDocument();
    view.unmount();

    // Same date range, but the vendor genuinely reported nothing: this is a
    // complete collection whose answer is zero, not a gap to re-run.
    (api.connections.collectionStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      status({
        status: "ok",
        reports: [
          report({
            latest_ok_period: null,
            latest_collected_period: "2026-07-31",
            ok_periods: 0,
            empty_periods: 30,
            rows_written: 0,
          }),
        ],
      }),
    );
    await renderRow();
    expect(await screen.findByTestId("collection-outcome")).toHaveTextContent(/ok/i);
    expect(screen.getByText(/collected through 2026-07-31 \(no rows\)/i)).toBeInTheDocument();
    expect(screen.queryByText(/not collected yet/i)).not.toBeInTheDocument();
  });

  it("shows the last run and the next scheduled hour", async () => {
    (api.connections.collectionStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      status({
        last_run_at: new Date(Date.now() - 3_600_000).toISOString(),
        next_scheduled_hour: 5,
      }),
    );
    await renderRow();
    await screen.findByTestId("collection-outcome");
    expect(screen.getByText(/1h ago/)).toBeInTheDocument();
    expect(screen.getByText(/05:00/)).toBeInTheDocument();
  });

  it("says auto-collect is off instead of inventing a next hour", async () => {
    (api.connections.collectionStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      status({ collection_enabled: false, next_scheduled_hour: null }),
    );
    await renderRow();
    await screen.findByTestId("collection-outcome");
    expect(screen.getByText(/auto-collect off/i)).toBeInTheDocument();
    expect(screen.queryByText(/next run/i)).not.toBeInTheDocument();
    // Still collectable on demand — pausing the schedule is not a lock.
    expect(screen.getByRole("button", { name: "Collect now" })).toBeEnabled();
  });

  it("lists the pending periods on a partial run", async () => {
    (api.connections.collectionStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      status({
        status: "partial",
        pending_periods: 2,
        reports: [
          report({
            latest_ok_period: "2026-07-29",
            latest_collected_period: "2026-07-29",
            ok_periods: 28,
            failed_periods: 2,
            pending_periods: 2,
            pending_sample: ["2026-07-30", "2026-07-31"],
            last_error: "GA4 quota exhausted",
          }),
        ],
      }),
    );
    await renderRow();
    await screen.findByTestId("collection-outcome");
    expect(screen.getByText(/2 pending/)).toBeInTheDocument();
    expect(screen.getByText(/2026-07-30/)).toBeInTheDocument();
    expect(screen.getByText(/2026-07-31/)).toBeInTheDocument();
    expect(screen.getByTestId("collection-error")).toHaveTextContent(
      /GA4 quota exhausted/,
    );
  });
});

describe("CollectionStatusRow — a caveat is not an error (SCN-115 honesty)", () => {
  it("renders a degraded caveat on an ok row as a caveat, with no error styling or alert role", async () => {
    (api.connections.collectionStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      status({
        status: "ok",
        caveat: "GA4 sampled this range — totals are approximate",
        reports: [
          report({
            report: "geo",
            caveat: "GA4 sampled this range — totals are approximate",
          }),
        ],
      }),
    );
    await renderRow();
    await screen.findByTestId("collection-outcome");

    // The connection-level `caveat` is the newest report-level caveat promoted
    // to the top of the payload, so it prints once — on the report that
    // produced it — and is not echoed a second time as a summary.
    const caveats = screen.getAllByTestId("collection-caveat");
    expect(caveats).toHaveLength(1);
    const caveat = caveats[0];
    expect(caveat).toHaveTextContent(/sampled this range/i);
    expect(caveat.className).not.toMatch(/error/);
    expect(caveat).not.toHaveAttribute("role", "alert");

    expect(screen.queryByTestId("collection-error")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByTestId("collection-outcome")).toHaveTextContent(/ok/i);
  });

  it("has no caveat or error to show when the journal is empty", async () => {
    // `caveat` / `last_error` are derived from journal rows, and every journal
    // row also produces a report — so "no reports" and "something to say" can
    // never co-occur. Nothing is rendered outside the report list.
    (api.connections.collectionStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      status({
        status: "never_collected",
        last_run_at: null,
        caveat: null,
        last_error: null,
        reports: [],
      }),
    );
    await renderRow();
    await screen.findByTestId("collection-outcome");

    expect(screen.queryByTestId("collection-caveat")).not.toBeInTheDocument();
    expect(screen.queryByTestId("collection-error")).not.toBeInTheDocument();
  });

  it("renders a truncation caveat the same way", async () => {
    (api.connections.collectionStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      status({
        status: "ok",
        reports: [
          report({
            report: "events",
            caveat: "Truncated — the vendor capped this range after paging",
          }),
        ],
      }),
    );
    await renderRow();
    await screen.findByTestId("collection-outcome");

    expect(screen.getByTestId("collection-caveat")).toHaveTextContent(/truncat/i);
    expect(screen.queryByTestId("collection-error")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does mark a real failure as an error", async () => {
    (api.connections.collectionStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      status({
        status: "failed",
        pending_periods: 30,
        last_error: "403: property not shared with the service account",
        reports: [
          report({
            latest_ok_period: null,
            latest_collected_period: null,
            ok_periods: 0,
            failed_periods: 30,
            rows_written: 0,
            pending_periods: 30,
            pending_sample: ["2026-07-31"],
            last_error: "403: property not shared with the service account",
          }),
        ],
      }),
    );
    await renderRow();
    await screen.findByTestId("collection-outcome");

    const err = screen.getByTestId("collection-error");
    expect(err).toHaveTextContent(/property not shared/i);
    expect(err).toHaveAttribute("role", "alert");
  });
});

describe("CollectionStatusRow — Collect now (SCN-115)", () => {
  it("calls the collect endpoint exactly once for a click", async () => {
    const user = userEvent.setup({ delay: null });
    await renderRow();
    const btn = await screen.findByRole("button", { name: "Collect now" });

    await user.click(btn);

    await waitFor(() => expect(api.connections.collectNow).toHaveBeenCalledTimes(1));
    expect(api.connections.collectNow).toHaveBeenCalledWith("c1");
  });

  it("enqueues exactly one job for an impatient double click", async () => {
    let release: () => void = () => {};
    (api.connections.collectNow as ReturnType<typeof vi.fn>).mockImplementation(
      () =>
        new Promise((resolve) => {
          release = () => resolve({ status: "queued" });
        }),
    );

    await renderRow();
    const btn = await screen.findByRole("button", { name: "Collect now" });

    // Both clicks land inside the same in-flight window: the second is a no-op.
    fireEvent.click(btn);
    fireEvent.click(btn);
    expect(api.connections.collectNow).toHaveBeenCalledTimes(1);

    await act(async () => {
      release();
    });
    expect(api.connections.collectNow).toHaveBeenCalledTimes(1);
  });

  it("toasts when collect fails and leaves the row usable", async () => {
    (api.connections.collectNow as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("worker unavailable"),
    );
    const user = userEvent.setup({ delay: null });
    await renderRow();
    const btn = await screen.findByRole("button", { name: "Collect now" });
    await user.click(btn);

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith("worker unavailable", "error"),
    );
    expect(screen.getByRole("button", { name: "Collect now" })).toBeEnabled();
  });

  it("offers a retry when the status fetch fails", async () => {
    (api.connections.collectionStatus as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("status unavailable"),
    );
    const user = userEvent.setup({ delay: null });
    await renderRow();
    await waitFor(() =>
      expect(screen.getByText("status unavailable")).toBeInTheDocument(),
    );

    (api.connections.collectionStatus as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      status({ status: "ok" }),
    );
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(screen.getByTestId("collection-outcome")).toHaveTextContent(/ok/i),
    );
  });
});
