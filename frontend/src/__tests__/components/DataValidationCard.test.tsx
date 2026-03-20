import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/api", () => ({
  api: {
    dataValidation: {
      validateData: vi.fn().mockResolvedValue({ ok: true, verdict: "confirmed" }),
    },
  },
}));

vi.mock("@/stores/app-store", () => ({
  useAppStore: Object.assign(
    () => ({}),
    {
      getState: () => ({
        activeProject: { id: "proj-1" },
        activeConnection: { id: "conn-1" },
      }),
    },
  ),
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

async function renderCard() {
  const { DataValidationCard } = await import(
    "@/components/chat/DataValidationCard"
  );
  return render(
    <DataValidationCard
      messageId="msg-1"
      query="SELECT count(*) FROM orders"
      sessionId="sess-1"
    />,
  );
}

describe("DataValidationCard", () => {
  it("renders quick action buttons", async () => {
    await renderCard();
    expect(screen.getByText("Looks correct")).toBeTruthy();
    expect(screen.getByText("Something's off")).toBeTruthy();
    expect(screen.getByText("Check later")).toBeTruthy();
  });

  it("confirms data and shows status", async () => {
    const user = userEvent.setup();
    await renderCard();
    await user.click(screen.getByText("Looks correct"));
    expect(await screen.findByText("Confirmed accurate")).toBeTruthy();
  });

  it("shows rejection form on 'Something's off'", async () => {
    const user = userEvent.setup();
    await renderCard();
    await user.click(screen.getByText("Something's off"));
    expect(screen.getByPlaceholderText("What did you expect? (optional)")).toBeTruthy();
    expect(screen.getByPlaceholderText("What seems wrong? (optional)")).toBeTruthy();
  });

  it("can cancel rejection form", async () => {
    const user = userEvent.setup();
    await renderCard();
    await user.click(screen.getByText("Something's off"));
    await user.click(screen.getByText("Cancel"));
    expect(screen.getByText("Looks correct")).toBeTruthy();
  });
});
