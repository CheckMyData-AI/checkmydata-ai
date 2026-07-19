import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastContainer } from "@/components/ui/ToastContainer";

const mockRemoveToast = vi.fn();
let mockToasts: Array<{ id: string; type: string; message: string }> = [];

vi.mock("@/stores/toast-store", () => ({
  useToastStore: () => ({
    toasts: mockToasts,
    removeToast: mockRemoveToast,
  }),
  toast: vi.fn(),
}));

describe("ToastContainer", () => {
  beforeEach(() => {
    mockToasts = [];
    mockRemoveToast.mockClear();
  });

  it("renders nothing when no toasts", () => {
    const { container } = render(<ToastContainer />);
    expect(container.innerHTML).toBe("");
  });

  it("renders success toast", () => {
    mockToasts = [{ id: "1", type: "success", message: "Saved!" }];
    render(<ToastContainer />);
    expect(screen.getByText("Saved!")).toBeInTheDocument();
  });

  it("renders error toast", () => {
    mockToasts = [{ id: "2", type: "error", message: "Failed!" }];
    render(<ToastContainer />);
    expect(screen.getByText("Failed!")).toBeInTheDocument();
  });

  it("renders multiple toasts", () => {
    mockToasts = [
      { id: "1", type: "success", message: "First" },
      { id: "2", type: "error", message: "Second" },
    ];
    render(<ToastContainer />);
    expect(screen.getByText("First")).toBeInTheDocument();
    expect(screen.getByText("Second")).toBeInTheDocument();
  });

  it("calls removeToast when dismiss button clicked", async () => {
    const user = userEvent.setup();
    mockToasts = [{ id: "42", type: "info", message: "Dismiss me" }];
    render(<ToastContainer />);
    const dismissBtn = screen.getByRole("button", { name: /dismiss notification/i });
    await user.click(dismissBtn);
    expect(mockRemoveToast).toHaveBeenCalledWith("42");
  });

  it("renders the 402 upgrade hint's /pricing as a clickable link (SCN-100)", () => {
    mockToasts = [
      {
        id: "402",
        type: "error",
        message: "Plan limit reached. Upgrade at /pricing to continue.",
      },
    ];
    render(<ToastContainer />);
    const link = screen.getByRole("link", { name: "/pricing" });
    expect(link).toHaveAttribute("href", "/pricing");
    // Surrounding copy is preserved.
    expect(screen.getByText(/Plan limit reached\./)).toBeInTheDocument();
    expect(screen.getByText(/to continue\./)).toBeInTheDocument();
  });
});
