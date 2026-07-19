import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import VerifyEmailPage from "@/app/verify-email/page";
import { useAuthStore } from "@/stores/auth-store";
import { api } from "@/lib/api";

// Mutable ?token= query the page reads (mock-prefixed for the hoisted factory).
let mockSearchString = "";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(mockSearchString),
}));

beforeEach(() => {
  vi.restoreAllMocks();
  mockSearchString = "";
  useAuthStore.setState({ user: null, token: null, isLoading: false, error: null });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("VerifyEmailPage (SCN-012)", () => {
  it("shows loading then success when the token verifies", async () => {
    mockSearchString = "token=good-token";
    let resolveVerify: (v: { ok: boolean; invites_accepted: number }) => void = () => {};
    const pending = new Promise<{ ok: boolean; invites_accepted: number }>((resolve) => {
      resolveVerify = resolve;
    });
    const spy = vi.spyOn(api.auth, "verifyEmail").mockReturnValue(pending);

    await act(async () => {
      render(<VerifyEmailPage />);
    });

    // Loading state is visible while the request is in flight.
    expect(screen.getByText("Verifying your email…")).toBeInTheDocument();

    await act(async () => {
      resolveVerify({ ok: true, invites_accepted: 0 });
      await pending;
    });

    await waitFor(() => {
      expect(screen.getByText("Email verified")).toBeInTheDocument();
    });
    expect(spy).toHaveBeenCalledWith("good-token");
    expect(screen.getByRole("link", { name: "Continue to app" })).toBeInTheDocument();
  });

  it("marks a logged-in user's cached profile verified on success", async () => {
    mockSearchString = "token=good-token";
    useAuthStore.setState({
      user: {
        id: "u1",
        email: "a@b.com",
        display_name: "A",
        auth_provider: "email",
        email_verified: false,
      },
    });
    vi.spyOn(api.auth, "verifyEmail").mockResolvedValue({ ok: true, invites_accepted: 1 });

    await act(async () => {
      render(<VerifyEmailPage />);
    });

    await waitFor(() => {
      expect(screen.getByText("Email verified")).toBeInTheDocument();
    });
    expect(useAuthStore.getState().user?.email_verified).toBe(true);
  });

  it("shows the error state when the token is invalid", async () => {
    mockSearchString = "token=bad-token";
    vi.spyOn(api.auth, "verifyEmail").mockRejectedValue(new Error("Invalid or expired"));

    await act(async () => {
      render(<VerifyEmailPage />);
    });

    await waitFor(() => {
      expect(screen.getByText("Verification failed")).toBeInTheDocument();
    });
    // Logged-out users are pointed back to sign in (no resend button).
    expect(screen.getByRole("link", { name: "Back to sign in" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Resend verification email" }),
    ).not.toBeInTheDocument();
  });

  it("shows the error state (no request) when no token is present", async () => {
    mockSearchString = "";
    const spy = vi.spyOn(api.auth, "verifyEmail");

    await act(async () => {
      render(<VerifyEmailPage />);
    });

    await waitFor(() => {
      expect(screen.getByText("Verification failed")).toBeInTheDocument();
    });
    expect(spy).not.toHaveBeenCalled();
  });

  it("offers a resend button on error when logged in", async () => {
    mockSearchString = "token=bad-token";
    useAuthStore.setState({
      user: {
        id: "u1",
        email: "a@b.com",
        display_name: "A",
        auth_provider: "email",
        email_verified: false,
      },
    });
    vi.spyOn(api.auth, "verifyEmail").mockRejectedValue(new Error("expired"));
    const resend = vi
      .spyOn(api.auth, "resendVerification")
      .mockResolvedValue({ ok: true, already_verified: false });

    await act(async () => {
      render(<VerifyEmailPage />);
    });

    await waitFor(() => {
      expect(screen.getByText("Verification failed")).toBeInTheDocument();
    });
    const btn = screen.getByRole("button", { name: "Resend verification email" });
    await act(async () => {
      btn.click();
    });
    expect(resend).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Resend verification email" }),
      ).toHaveTextContent("Email sent");
    });
  });
});
