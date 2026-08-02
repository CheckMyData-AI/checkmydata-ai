/**
 * SCN-114 (add / delete a vendor credential) and SCN-116 (delete refused while a
 * connection still references it).
 *
 * The load-bearing assertion is the write-only one: whatever is pasted into the
 * service-account box must never come back out of the DOM.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/api/vendor-credentials", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/vendor-credentials")>(
    "@/lib/api/vendor-credentials",
  );
  return {
    ...actual,
    vendorCredentials: {
      list: vi.fn().mockResolvedValue([]),
      create: vi.fn(),
      delete: vi.fn(),
    },
  };
});

vi.mock("@/stores/toast-store", () => ({ toast: vi.fn() }));

vi.mock("@/components/ui/ConfirmModal", () => ({
  confirmAction: vi.fn().mockResolvedValue(true),
}));

vi.mock("@/components/ui/Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

vi.mock("@/components/ui/ActionButton", () => ({
  ActionButton: ({
    icon,
    title,
    onClick,
  }: {
    icon: string;
    title: string;
    onClick: (e: React.MouseEvent) => void;
  }) => (
    <button data-testid={`action-${icon}`} aria-label={title} onClick={onClick}>
      {icon}
    </button>
  ),
}));

const { vendorCredentials } = await import("@/lib/api/vendor-credentials");
const { toast } = await import("@/stores/toast-store");
const { confirmAction } = await import("@/components/ui/ConfirmModal");

const CREDENTIAL = {
  id: "vc1",
  name: "analytics-sa",
  provider: "ga4",
  fingerprint: "abc123def4567890",
  meta: { client_email: "collector@proj.iam.gserviceaccount.com" },
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const IN_USE_MESSAGE =
  "Cannot delete: this credential is in use by a connection. " +
  "Delete or re-point the connection first.";

beforeEach(() => {
  vi.clearAllMocks();
  (vendorCredentials.list as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (confirmAction as ReturnType<typeof vi.fn>).mockResolvedValue(true);
});

async function renderPanel() {
  const { VendorCredentialsPanel } = await import(
    "@/components/settings/VendorCredentialsPanel"
  );
  return render(<VendorCredentialsPanel />);
}

describe("VendorCredentialsPanel (SCN-114)", () => {
  it("shows the empty state when nothing is stored", async () => {
    await renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/no vendor credentials/i)).toBeInTheDocument(),
    );
  });

  it("shows an inline retry when the list fails to load", async () => {
    (vendorCredentials.list as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("backend down"),
    );
    await renderPanel();
    await waitFor(() => expect(screen.getByText("backend down")).toBeInTheDocument());

    (vendorCredentials.list as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      CREDENTIAL,
    ]);
    const user = userEvent.setup({ delay: null });
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByText("analytics-sa")).toBeInTheDocument());
  });

  it("renders provider, fingerprint and the service-account email — never a secret", async () => {
    (vendorCredentials.list as ReturnType<typeof vi.fn>).mockResolvedValue([CREDENTIAL]);
    await renderPanel();

    await waitFor(() => expect(screen.getByText("analytics-sa")).toBeInTheDocument());
    expect(screen.getByText("GA4")).toBeInTheDocument();
    expect(screen.getByText(/abc123de/)).toBeInTheDocument();
    expect(
      screen.getByText("collector@proj.iam.gserviceaccount.com"),
    ).toBeInTheDocument();
  });

  it("creates a credential and never renders the pasted JSON back", async () => {
    const secret = JSON.stringify({
      type: "service_account",
      client_email: "collector@proj.iam.gserviceaccount.com",
      private_key: "-----BEGIN PRIVATE KEY-----SUPERSECRETVALUE-----END PRIVATE KEY-----",
    });
    (vendorCredentials.create as ReturnType<typeof vi.fn>).mockResolvedValue(CREDENTIAL);

    const user = userEvent.setup({ delay: null });
    await renderPanel();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /add/i })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /^add$/i }));

    fireEvent.change(screen.getByLabelText("Credential name"), {
      target: { value: "analytics-sa" },
    });
    fireEvent.change(screen.getByLabelText("Credential provider"), {
      target: { value: "ga4" },
    });
    const textarea = screen.getByLabelText("Service account JSON");
    fireEvent.change(textarea, { target: { value: secret } });

    await user.click(screen.getByRole("button", { name: "Add credential" }));

    await waitFor(() =>
      expect(vendorCredentials.create).toHaveBeenCalledWith({
        name: "analytics-sa",
        provider: "ga4",
        secret,
      }),
    );
    await waitFor(() => expect(screen.getByText("analytics-sa")).toBeInTheDocument());

    expect(document.body.textContent).not.toContain("SUPERSECRETVALUE");
    expect(document.body.innerHTML).not.toContain("SUPERSECRETVALUE");
    expect(document.querySelectorAll("textarea").length).toBe(0);
  });

  it("surfaces the 422 message inline and keeps the pasted value for a fix", async () => {
    (vendorCredentials.create as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("ga4 credential must be a JSON service-account key"),
    );

    const user = userEvent.setup({ delay: null });
    await renderPanel();
    await user.click(screen.getByRole("button", { name: /^add$/i }));

    fireEvent.change(screen.getByLabelText("Credential name"), {
      target: { value: "broken" },
    });
    fireEvent.change(screen.getByLabelText("Service account JSON"), {
      target: { value: "not json" },
    });
    await user.click(screen.getByRole("button", { name: "Add credential" }));

    await waitFor(() =>
      expect(
        screen.getByText(/must be a JSON service-account key/i),
      ).toBeInTheDocument(),
    );
    expect(
      (screen.getByLabelText("Service account JSON") as HTMLTextAreaElement).value,
    ).toBe("not json");
  });

  it("says what is missing on submit instead of refusing silently", async () => {
    const user = userEvent.setup({ delay: null });
    await renderPanel();
    await user.click(screen.getByRole("button", { name: /^add$/i }));

    const submit = screen.getByRole("button", { name: "Add credential" });
    // A disabled button is a refusal with no explanation: the user is left
    // clicking a dead control with nothing telling them why.
    expect(submit).toBeEnabled();

    await user.click(submit);

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        /name and the credential itself are both required/i,
      ),
    );
    expect(vendorCredentials.create).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Credential name")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByLabelText("Service account JSON")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("flags only the field that is actually missing", async () => {
    const user = userEvent.setup({ delay: null });
    await renderPanel();
    await user.click(screen.getByRole("button", { name: /^add$/i }));

    fireEvent.change(screen.getByLabelText("Credential name"), {
      target: { value: "analytics-sa" },
    });
    await user.click(screen.getByRole("button", { name: "Add credential" }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByLabelText("Credential name")).not.toHaveAttribute("aria-invalid");
    expect(screen.getByLabelText("Service account JSON")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(vendorCredentials.create).not.toHaveBeenCalled();
  });

  it("deletes an unreferenced credential", async () => {
    (vendorCredentials.list as ReturnType<typeof vi.fn>).mockResolvedValue([CREDENTIAL]);
    (vendorCredentials.delete as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true });

    const user = userEvent.setup({ delay: null });
    await renderPanel();
    await waitFor(() => expect(screen.getByText("analytics-sa")).toBeInTheDocument());

    await user.click(screen.getByLabelText("Delete credential"));

    await waitFor(() => expect(vendorCredentials.delete).toHaveBeenCalledWith("vc1"));
    await waitFor(() =>
      expect(screen.queryByText("analytics-sa")).not.toBeInTheDocument(),
    );
  });
});

describe("VendorCredentialsPanel — delete blocked while in use (SCN-116)", () => {
  it("surfaces the in-use conflict and leaves the row in place", async () => {
    (vendorCredentials.list as ReturnType<typeof vi.fn>).mockResolvedValue([CREDENTIAL]);
    (vendorCredentials.delete as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error(IN_USE_MESSAGE),
    );

    const user = userEvent.setup({ delay: null });
    await renderPanel();
    await waitFor(() => expect(screen.getByText("analytics-sa")).toBeInTheDocument());

    await user.click(screen.getByLabelText("Delete credential"));

    await waitFor(() =>
      expect(screen.getByText(/in use by a connection/i)).toBeInTheDocument(),
    );
    // The credential is still there — nothing was orphaned, nothing was removed.
    expect(screen.getByText("analytics-sa")).toBeInTheDocument();
    expect(toast).toHaveBeenCalledWith(
      expect.stringMatching(/in use by a connection/i),
      "error",
    );
  });
});
