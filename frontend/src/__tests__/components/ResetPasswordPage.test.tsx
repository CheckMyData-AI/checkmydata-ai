import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render,
  screen,
  waitFor,
  act,
  fireEvent,
} from "@testing-library/react";
import ResetPasswordPage from "@/app/reset-password/page";
import { api } from "@/lib/api";
import { useToastStore } from "@/stores/toast-store";

const mockReplace = vi.fn();
// Mutable so each test drives the ?token= query the page reads. Must be
// `mock`-prefixed to be referenceable inside the hoisted vi.mock factory.
let mockSearchString = "";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    replace: mockReplace,
    push: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(mockSearchString),
}));

beforeEach(() => {
  vi.restoreAllMocks();
  mockReplace.mockClear();
  mockSearchString = "";
  useToastStore.setState({ toasts: [] });
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function fillPasswords(pw: string, confirm: string) {
  fireEvent.change(screen.getByLabelText("New password"), {
    target: { value: pw },
  });
  fireEvent.change(screen.getByLabelText("Confirm new password"), {
    target: { value: confirm },
  });
}

describe("ResetPasswordPage (SCN-013)", () => {
  it("resets the password then toasts and redirects to /login", async () => {
    mockSearchString = "token=good-token";
    const spy = vi
      .spyOn(api.auth, "resetPassword")
      .mockResolvedValue({ ok: true });

    await act(async () => {
      render(<ResetPasswordPage />);
    });

    await fillPasswords("brandnew999", "brandnew999");
    await act(async () => {
      fireEvent.submit(
        screen.getByRole("button", { name: "Reset password" }),
      );
    });

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login");
    });
    expect(spy).toHaveBeenCalledWith("good-token", "brandnew999");
    // A success toast is queued.
    expect(
      useToastStore.getState().toasts.some((t) => t.type === "success"),
    ).toBe(true);
  });

  it("shows an error with a recovery link when the token is invalid/expired", async () => {
    mockSearchString = "token=bad-token";
    vi.spyOn(api.auth, "resetPassword").mockRejectedValue(
      new Error("This password reset link is invalid or has expired."),
    );

    await act(async () => {
      render(<ResetPasswordPage />);
    });

    await fillPasswords("brandnew999", "brandnew999");
    await act(async () => {
      fireEvent.submit(
        screen.getByRole("button", { name: "Reset password" }),
      );
    });

    await waitFor(() => {
      expect(
        screen.getByText(/invalid or has expired/i),
      ).toBeInTheDocument();
    });
    expect(mockReplace).not.toHaveBeenCalled();
    expect(
      screen.getByRole("link", { name: "Request a new reset link" }),
    ).toBeInTheDocument();
  });

  it("shows an inline error and does not submit when the password is too short", async () => {
    mockSearchString = "token=good-token";
    const spy = vi.spyOn(api.auth, "resetPassword");

    await act(async () => {
      render(<ResetPasswordPage />);
    });

    await fillPasswords("short", "short");
    await act(async () => {
      fireEvent.submit(
        screen.getByRole("button", { name: "Reset password" }),
      );
    });

    await waitFor(() => {
      expect(
        screen.getAllByText(/at least 8 characters/i).length,
      ).toBeGreaterThan(0);
    });
    expect(spy).not.toHaveBeenCalled();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("shows the invalid-link state when no token is present", async () => {
    mockSearchString = "";

    await act(async () => {
      render(<ResetPasswordPage />);
    });

    expect(screen.getByText("Invalid reset link")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Request a new link" }),
    ).toBeInTheDocument();
    // The password form must not render without a token.
    expect(screen.queryByLabelText("New password")).not.toBeInTheDocument();
  });
});
