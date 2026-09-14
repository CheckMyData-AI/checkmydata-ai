/**
 * An unverified account is one click from creating a project; it was told to wait.
 *
 * `User.can_create_projects` defaults to `false` and is granted BY email
 * verification (`auth_service.verify_email`) — so for an email/password signup the
 * right to create arrives when a link in the inbox is clicked, and from nowhere
 * else. The backend has said so since F-PROJ-01, with two distinct 403 messages
 * (`projects.py:152-166`).
 *
 * The interface collapsed them into one: *"Project creation requires approval …
 * you need to be approved first"*, with **Request project access** as the only
 * button — an endpoint whose whole body sends an email to a human
 * (`projects.py:224-240`). So the one group that could help itself was pointed at
 * a waitlist, and the product's basic loop could not start at all for that group.
 *
 * Google sign-in sets both flags, which is why this was invisible to anyone who
 * tested with Google.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const mockAuthState: { user: Record<string, unknown> } = { user: {} };
vi.mock("@/stores/auth-store", () => ({
  useAuthStore: Object.assign(
    (selector?: (s: typeof mockAuthState) => unknown) =>
      selector ? selector(mockAuthState) : mockAuthState,
    { setState: vi.fn(), getState: () => mockAuthState },
  ),
}));

const resendVerification = vi.fn().mockResolvedValue({ ok: true, email_sent: true });
vi.mock("@/lib/api", () => ({ api: { auth: { resendVerification } } }));

const pushToast = vi.fn();
vi.mock("@/stores/toast-store", () => ({
  toast: (...args: unknown[]) => pushToast(...args),
  useToastStore: Object.assign((sel?: (s: unknown) => unknown) => (sel ? sel({}) : {}), {
    setState: vi.fn(),
    getState: () => ({}),
  }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  mockAuthState.user = { id: "u1", email: "someone@example.com", email_verified: false };
});

describe("the reason a user cannot create a project", () => {
  it("offers verification, not a waitlist, to an unverified account", async () => {
    const { VerifyEmailNeededModal } = await import(
      "@/components/auth/VerifyEmailNeededModal"
    );
    render(<VerifyEmailNeededModal open onClose={() => {}} />);

    expect(screen.getByText(/verify your email/i)).toBeTruthy();
    expect(screen.getByText("someone@example.com")).toBeTruthy();
    // The words that sent people to a human must not appear.
    expect(screen.queryByText(/requires approval/i)).toBeNull();
    expect(screen.queryByText(/request project access/i)).toBeNull();
    expect(screen.getByRole("button", { name: /resend verification/i })).toBeTruthy();
  });
});

describe("the resend button reports what actually happened", () => {
  it("says sent when the provider accepted it", async () => {
    resendVerification.mockResolvedValueOnce({ ok: true, email_sent: true });
    const { ResendVerificationButton } = await import(
      "@/components/auth/ResendVerificationButton"
    );
    const userEvent = (await import("@testing-library/user-event")).default;
    render(<ResendVerificationButton />);
    await userEvent.click(screen.getByRole("button"));
    expect(pushToast).toHaveBeenCalledWith(expect.stringMatching(/check your inbox/i), "success");
  });

  it("does NOT say sent when the provider refused", async () => {
    // `EmailService._send` returns false with no provider configured and after its
    // retries are spent. The route used to answer {ok: true} either way, so the
    // banner claimed delivery of a mail that was never dispatched — to the one
    // account type that cannot proceed without it.
    resendVerification.mockResolvedValueOnce({ ok: true, email_sent: false });
    const { ResendVerificationButton } = await import(
      "@/components/auth/ResendVerificationButton"
    );
    const userEvent = (await import("@testing-library/user-event")).default;
    render(<ResendVerificationButton />);
    await userEvent.click(screen.getByRole("button"));
    expect(pushToast).toHaveBeenCalledWith(
      expect.stringMatching(/could not send/i),
      "error",
    );
    expect(pushToast).not.toHaveBeenCalledWith(
      expect.stringMatching(/check your inbox/i),
      "success",
    );
  });
});
