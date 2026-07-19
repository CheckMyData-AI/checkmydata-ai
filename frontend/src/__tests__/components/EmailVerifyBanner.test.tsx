import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { EmailVerifyBanner } from "@/components/auth/EmailVerifyBanner";
import { useAuthStore } from "@/stores/auth-store";
import { useToastStore } from "@/stores/toast-store";
import { api } from "@/lib/api";
import type { AuthUser } from "@/lib/api";

function makeUser(overrides: Partial<AuthUser> = {}): AuthUser {
  return {
    id: "u1",
    email: "a@b.com",
    display_name: "A",
    auth_provider: "email",
    email_verified: false,
    ...overrides,
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
  useAuthStore.setState({ user: null, token: null, isLoading: false, error: null });
  useToastStore.setState({ toasts: [] });
});

describe("EmailVerifyBanner (SCN-012)", () => {
  it("is hidden when there is no user", () => {
    const { container } = render(<EmailVerifyBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("is hidden for a verified account", () => {
    useAuthStore.setState({ user: makeUser({ email_verified: true }) });
    const { container } = render(<EmailVerifyBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("is hidden for a Google account", () => {
    useAuthStore.setState({
      user: makeUser({ auth_provider: "google", email_verified: false }),
    });
    const { container } = render(<EmailVerifyBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("is hidden when email_verified is unknown (undefined)", () => {
    useAuthStore.setState({ user: makeUser({ email_verified: undefined }) });
    const { container } = render(<EmailVerifyBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows for an unverified email account and resends on click", async () => {
    const spy = vi
      .spyOn(api.auth, "resendVerification")
      .mockResolvedValue({ ok: true, already_verified: false });
    useAuthStore.setState({ user: makeUser({ email_verified: false }) });

    render(<EmailVerifyBanner />);
    const btn = screen.getByRole("button", { name: "Resend verification email" });
    expect(btn).toBeInTheDocument();

    await act(async () => {
      btn.click();
    });

    expect(spy).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Resend verification email" }),
      ).toHaveTextContent("Email sent");
    });
    // A success toast is queued.
    const toasts = useToastStore.getState().toasts;
    expect(toasts.some((t) => t.type === "success")).toBe(true);
  });

  it("surfaces an error toast when resend fails", async () => {
    vi.spyOn(api.auth, "resendVerification").mockRejectedValue(
      new Error("Server error"),
    );
    useAuthStore.setState({ user: makeUser({ email_verified: false }) });

    render(<EmailVerifyBanner />);
    await act(async () => {
      screen.getByRole("button", { name: "Resend verification email" }).click();
    });

    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts.some((t) => t.type === "error")).toBe(true);
    });
  });
});
