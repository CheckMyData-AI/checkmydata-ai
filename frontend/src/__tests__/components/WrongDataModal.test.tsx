import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Track D1: the "this data is wrong" investigation, mounted on thumbs-down.
 *
 * The component and its three endpoints shipped long ago and nothing imported it —
 * the largest block of finished-but-unreachable product in the repository. These are
 * its first tests, because until now nothing could reach it to break.
 */

vi.mock("@/lib/api", () => ({
  api: {
    dataValidation: {
      startInvestigation: vi.fn().mockResolvedValue({ investigation_id: "inv1" }),
      getInvestigation: vi.fn().mockResolvedValue({
        id: "inv1",
        status: "presenting_fix",
        root_cause: "The filter excluded refunded rows",
        corrected_query: "SELECT count(*) FROM purchases",
        original_result: { columns: ["n"], rows: [[10]] },
        corrected_result: { columns: ["n"], rows: [[12]] },
      }),
      confirmFix: vi.fn().mockResolvedValue({ ok: true, status: "confirmed" }),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({ toast: vi.fn() }));

vi.mock("@/stores/app-store", () => {
  const state = {
    activeProject: { id: "proj1", name: "P" },
    activeConnection: { id: "conn1" },
  };
  const useAppStore = Object.assign(() => state, { getState: () => state });
  return { useAppStore };
});

const { WrongDataModal } = await import("@/components/chat/WrongDataModal");

const FAST = { intervalMs: 5, slowAfterMs: 20, giveUpAfterMs: 120, maxConsecutiveErrors: 3 };

function open(onClose = vi.fn(), pollTiming?: typeof FAST) {
  render(
    <WrongDataModal
      messageId="msg1"
      query="SELECT count(*) FROM purchases"
      sessionId="sess1"
      resultColumns={["n"]}
      onClose={onClose}
      pollTiming={pollTiming}
    />,
  );
  return onClose;
}

async function start() {
  await userEvent.click(screen.getByText("Numbers too low"));
  await userEvent.click(screen.getByRole("button", { name: /investigat/i }));
}

describe("WrongDataModal", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(cleanup);

  it("is a dialog the keyboard can leave", async () => {
    const onClose = open();
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");

    await userEvent.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalled();
  });

  it("will not start an investigation before the reader says what is wrong", async () => {
    const { api } = await import("@/lib/api");
    open();

    const start = screen.getByRole("button", { name: /investigat/i });
    expect(start).toBeDisabled();

    await userEvent.click(screen.getByText("Numbers too low"));
    expect(start).toBeEnabled();
    await userEvent.click(start);

    await waitFor(() =>
      expect(api.dataValidation.startInvestigation).toHaveBeenCalledWith(
        expect.objectContaining({
          project_id: "proj1",
          connection_id: "conn1",
          session_id: "sess1",
          message_id: "msg1",
          complaint_type: "numbers_too_low",
        }),
      ),
    );
  });

  it("reads the investigation back within the project that owns it", async () => {
    // The route re-scopes every id to a project the caller belongs to and answers 404
    // rather than confirming another tenant's investigation exists, so `project_id` is
    // required. Without it the poll is a 422 — which is what it was until Track D1
    // mounted this component and a real investigation could not be read back.
    const { api } = await import("@/lib/api");
    open();

    await userEvent.click(screen.getByText("Numbers too low"));
    await userEvent.click(screen.getByRole("button", { name: /investigat/i }));

    await waitFor(
      () => expect(api.dataValidation.getInvestigation).toHaveBeenCalledWith("inv1", "proj1"),
      { timeout: 6000 },
    );
  });

  it("shows the cause and both results once the investigation finishes", async () => {
    open();

    await userEvent.click(screen.getByText("Numbers too low"));
    await userEvent.click(screen.getByRole("button", { name: /investigat/i }));

    // The poll sleeps 2 s between reads, which is the component's own pace.
    expect(
      await screen.findByText(/The filter excluded refunded rows/, {}, { timeout: 6000 }),
    ).toBeInTheDocument();
  });

  // T04b (audit 2026-09-23 §3.3): the modal used to wait 60 s, or stop at the first
  // failed read, and then sit on "investigating" for ever.

  it("names its fields for a screen reader and says which complaint is chosen", async () => {
    open();
    expect(screen.getByLabelText("Expected value (optional)")).toBeInTheDocument();
    expect(screen.getByLabelText("Which column? (optional)")).toBeInTheDocument();
    const choice = screen.getByRole("button", { name: /Numbers too low/ });
    expect(choice).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(choice);
    expect(choice).toHaveAttribute("aria-pressed", "true");
  });

  it("says it is slow, then offers to look again instead of spinning for ever", async () => {
    const { api } = await import("@/lib/api");
    vi.mocked(api.dataValidation.getInvestigation).mockResolvedValue({ id: "inv1", status: "investigating" });
    open(vi.fn(), FAST);
    await start();

    expect(await screen.findByText(/can take a few minutes/)).toBeInTheDocument();
    const again = await screen.findByRole("button", { name: "Check again" });

    vi.mocked(api.dataValidation.getInvestigation).mockResolvedValue({
      id: "inv1",
      status: "presenting_fix",
      root_cause: "Found it on the second look",
    });
    await userEvent.click(again);
    expect(await screen.findByText(/Found it on the second look/)).toBeInTheDocument();
  });

  it("survives a failed read, and says so after three in a row", async () => {
    const { api } = await import("@/lib/api");
    const get = vi.mocked(api.dataValidation.getInvestigation);
    get.mockRejectedValueOnce(new Error("502")).mockResolvedValue({ id: "inv1", status: "investigating" });
    open(vi.fn(), { ...FAST, giveUpAfterMs: 60_000, slowAfterMs: 60_000 });
    await start();
    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(2));
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();

    get.mockRejectedValue(new Error("offline"));
    expect(await screen.findByText(/Couldn't reach the server/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
