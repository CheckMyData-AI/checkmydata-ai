import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { useAuthStore } from "@/stores/auth-store";

const mockReplace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace, push: vi.fn(), back: vi.fn(), forward: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/app",
  useSearchParams: () => new URLSearchParams(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({
    user: null,
    token: null,
    isLoading: false,
    error: null,
    restore: async () => {},
  });
});

async function renderAuthGate() {
  const { AuthGate } = await import("@/components/auth/AuthGate");
  await act(async () => {
    render(
      <AuthGate>
        <div data-testid="child-content">Protected</div>
      </AuthGate>,
    );
  });
}

describe("AuthGate", () => {
  it("redirects to /login when user is null", async () => {
    await renderAuthGate();
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login");
    });
  });

  it("does not render children when user is null", async () => {
    await renderAuthGate();
    await waitFor(() => {
      expect(screen.queryByTestId("child-content")).not.toBeInTheDocument();
    });
  });

  it("shows redirecting text while navigating to login", async () => {
    await renderAuthGate();
    await waitFor(() => {
      expect(screen.getByText("Redirecting...")).toBeInTheDocument();
    });
  });

  it("renders children when user is logged in", async () => {
    const user = { id: "u1", email: "a@b.com", display_name: "A" };
    useAuthStore.setState({
      user,
      token: "tok",
      restore: async () => {
        useAuthStore.setState({ user, token: "tok" });
      },
    });
    await renderAuthGate();
    await waitFor(() => {
      expect(screen.getByTestId("child-content")).toBeInTheDocument();
    });
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("shows loading state while restoring", async () => {
    useAuthStore.setState({
      restore: () => new Promise(() => {}),
    });
    await renderAuthGate();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });
});
