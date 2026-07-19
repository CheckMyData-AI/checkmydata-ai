import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render,
  screen,
  waitFor,
  act,
  fireEvent,
} from "@testing-library/react";
import ForgotPasswordPage from "@/app/forgot-password/page";
import { api } from "@/lib/api";

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ForgotPasswordPage (SCN-013)", () => {
  it("shows a generic confirmation after a successful submit", async () => {
    const spy = vi
      .spyOn(api.auth, "forgotPassword")
      .mockResolvedValue({ ok: true });

    await act(async () => {
      render(<ForgotPasswordPage />);
    });

    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "user@example.com" },
    });
    await act(async () => {
      fireEvent.submit(screen.getByRole("button", { name: "Send reset link" }));
    });

    await waitFor(() => {
      expect(screen.getByText("Check your email")).toBeInTheDocument();
    });
    expect(spy).toHaveBeenCalledWith("user@example.com");
    // Generic copy — must not reveal whether the account exists.
    expect(
      screen.getByText(/If an account exists for that address/i),
    ).toBeInTheDocument();
  });

  it("surfaces an error when the request fails", async () => {
    vi.spyOn(api.auth, "forgotPassword").mockRejectedValue(
      new Error("Too many requests. Please wait a moment and try again."),
    );

    await act(async () => {
      render(<ForgotPasswordPage />);
    });

    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "user@example.com" },
    });
    await act(async () => {
      fireEvent.submit(screen.getByRole("button", { name: "Send reset link" }));
    });

    await waitFor(() => {
      expect(screen.getByText(/Too many requests/i)).toBeInTheDocument();
    });
    // No success confirmation on the error path.
    expect(screen.queryByText("Check your email")).not.toBeInTheDocument();
  });

  it("shows an inline validation error and does not call the API for a bad email", async () => {
    const spy = vi.spyOn(api.auth, "forgotPassword");

    await act(async () => {
      render(<ForgotPasswordPage />);
    });

    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "not-an-email" },
    });
    await act(async () => {
      fireEvent.submit(screen.getByRole("button", { name: "Send reset link" }));
    });

    await waitFor(() => {
      expect(
        screen.getByText("Please enter a valid email address"),
      ).toBeInTheDocument();
    });
    expect(spy).not.toHaveBeenCalled();
  });
});
