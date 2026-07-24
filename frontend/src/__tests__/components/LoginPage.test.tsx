import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";

const mockReplace = vi.fn();
// Mutable so each test can drive the ?next= query the page reads. Must be
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

const initialize = vi.fn();
const renderButton = vi.fn();

function installGoogleGis() {
  (window as unknown as { google: unknown }).google = {
    accounts: {
      id: { initialize, renderButton, prompt: vi.fn(), disableAutoSelect: vi.fn() },
    },
  };
}

interface SetupOptions {
  clientId: string;
  restore: () => Promise<void>;
}

// Import the store and the page from a freshly-reset module registry so that
// (a) the page picks up the stubbed NEXT_PUBLIC_GOOGLE_CLIENT_ID (read at
// module load) and (b) the store instance we configure is the SAME one the
// page imports.
async function setupAndRender(opts: SetupOptions) {
  vi.resetModules();
  vi.stubEnv("NEXT_PUBLIC_GOOGLE_CLIENT_ID", opts.clientId);

  const { useAuthStore } = await import("@/stores/auth-store");
  useAuthStore.setState({
    user: null,
    token: null,
    isLoading: false,
    error: null,
    restore: opts.restore,
    login: async () => {},
    register: async () => {},
    googleLogin: async () => {},
  });

  const LoginPage = (await import("@/app/login/page")).default;
  await act(async () => {
    render(<LoginPage />);
  });
  return { useAuthStore };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockSearchString = "";
});

afterEach(() => {
  vi.unstubAllEnvs();
  delete (window as unknown as { google?: unknown }).google;
});

describe("LoginPage Google sign-in", () => {
  it("renders the Google button after auth restore completes, even when the GIS script is already loaded (warm navigation)", async () => {
    // Simulate a warm navigation where the GIS script is already present.
    // This is the exact condition under which the button used to vanish:
    // the init effect ran while the page still showed the restore spinner
    // (button container not mounted), bailed against a null ref, and — with
    // the script already cached — never retried.
    installGoogleGis();

    let resolveRestore: () => void = () => {};
    const restorePromise = new Promise<void>((resolve) => {
      resolveRestore = resolve;
    });

    await setupAndRender({
      clientId: "test-client.apps.googleusercontent.com",
      restore: () => restorePromise,
    });

    // While restoring, only the spinner is mounted — the Google button
    // container does not exist yet, so it must not have been rendered.
    expect(renderButton).not.toHaveBeenCalled();

    await act(async () => {
      resolveRestore();
      await restorePromise;
    });

    await waitFor(() => {
      expect(renderButton).toHaveBeenCalledTimes(1);
    });
    expect(initialize).toHaveBeenCalledTimes(1);
  });

  it("does not render the Google button when no client id is configured", async () => {
    installGoogleGis();

    await setupAndRender({
      clientId: "",
      restore: async () => {},
    });

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Sign In" }),
      ).toBeInTheDocument();
    });
    // The "or" divider only renders inside the Google-enabled block.
    expect(screen.queryByText("or")).not.toBeInTheDocument();
    expect(renderButton).not.toHaveBeenCalled();
    expect(initialize).not.toHaveBeenCalled();
  });
});

describe("LoginPage post-auth redirect (SCN-098/110)", () => {
  const LOGGED_IN = { id: "u1", email: "a@b.com", display_name: "A" };

  async function renderThenAuthenticate(next: string) {
    mockSearchString = next;
    const { useAuthStore } = await setupAndRender({
      clientId: "",
      restore: async () => {},
    });
    // Simulate a successful login/register: the store sets `user`, which
    // triggers the page's redirect effect.
    await act(async () => {
      useAuthStore.setState({ user: LOGGED_IN });
    });
  }

  it("honors a safe same-origin `next` path", async () => {
    await renderThenAuthenticate("next=/pricing");
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/pricing");
    });
  });

  it("rejects a protocol-relative `next` (open-redirect guard) and falls back to /app", async () => {
    await renderThenAuthenticate("next=//evil.com");
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/app");
    });
    expect(mockReplace).not.toHaveBeenCalledWith("//evil.com");
  });

  it("rejects an absolute-URL `next` and falls back to /app", async () => {
    await renderThenAuthenticate("next=https://evil.com");
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/app");
    });
    expect(mockReplace).not.toHaveBeenCalledWith("https://evil.com");
  });

  it("rejects a backslash protocol-relative `next` and falls back to /app", async () => {
    await renderThenAuthenticate("next=/\\evil.com");
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/app");
    });
  });

  it("defaults to /app when no `next` is present", async () => {
    await renderThenAuthenticate("");
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/app");
    });
  });
});

describe("LoginPage forgot-password link (SCN-013)", () => {
  it("shows a 'Forgot password?' link to /forgot-password in sign-in mode", async () => {
    await setupAndRender({ clientId: "", restore: async () => {} });

    const link = await screen.findByRole("link", { name: "Forgot password?" });
    expect(link).toHaveAttribute("href", "/forgot-password");
  });

  it("hides the 'Forgot password?' link in register mode", async () => {
    await setupAndRender({ clientId: "", restore: async () => {} });

    await screen.findByRole("link", { name: "Forgot password?" });
    // Switch to the Create Account (register) mode.
    await act(async () => {
      screen.getByRole("button", { name: "Register" }).click();
    });

    expect(
      screen.queryByRole("link", { name: "Forgot password?" }),
    ).not.toBeInTheDocument();
  });
});

describe("LoginPage session-expired flash (FA-010)", () => {
  it("shows the stashed session-expired message once and clears it", async () => {
    sessionStorage.setItem(
      "cmd_session_flash",
      "Your session has expired. Please log in again.",
    );

    await setupAndRender({ clientId: "", restore: async () => {} });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Your session has expired. Please log in again.",
    );
    // Consumed on mount — a reload must not show it again.
    expect(sessionStorage.getItem("cmd_session_flash")).toBeNull();
  });

  it("renders no flash banner when nothing was stashed", async () => {
    await setupAndRender({ clientId: "", restore: async () => {} });

    await screen.findByRole("button", { name: "Sign In" });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
