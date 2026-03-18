import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useAuthStore } from "@/stores/auth-store";

vi.mock("@/lib/api", () => ({
  api: {
    auth: {
      login: vi.fn().mockResolvedValue({ token: "t", user: { id: "u1", email: "a@b.com", display_name: "A" } }),
      register: vi.fn().mockResolvedValue({ token: "t", user: { id: "u1", email: "a@b.com", display_name: "A" } }),
      googleLogin: vi.fn().mockResolvedValue({ token: "t", user: { id: "u1", email: "a@b.com", display_name: "A" } }),
    },
  },
}));

vi.mock("@/components/ui/Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: null, token: null, isLoading: false, error: null });
});

async function renderAuthGate() {
  const { AuthGate } = await import("@/components/auth/AuthGate");
  return render(
    <AuthGate>
      <div data-testid="child-content">Protected</div>
    </AuthGate>,
  );
}

describe("AuthGate", () => {
  it("renders login form when user is null", async () => {
    await renderAuthGate();
    expect(screen.getByRole("heading", { name: "Sign In" })).toBeInTheDocument();
  });

  it("can switch to register form", async () => {
    await renderAuthGate();
    await userEvent.click(screen.getByText("Register"));
    expect(screen.getByRole("heading", { name: "Create Account" })).toBeInTheDocument();
  });

  it("shows email and password inputs", async () => {
    await renderAuthGate();
    expect(screen.getByPlaceholderText("Email")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Password")).toBeInTheDocument();
  });

  it("has submit button", async () => {
    await renderAuthGate();
    const submitBtn = screen.getByRole("button", { name: "Sign In" });
    expect(submitBtn).toBeInTheDocument();
  });

  it("shows display name input in register mode", async () => {
    await renderAuthGate();
    await userEvent.click(screen.getByText("Register"));
    expect(screen.getByPlaceholderText("Display Name")).toBeInTheDocument();
  });

  it("displays error message from store", async () => {
    useAuthStore.setState({ error: "Invalid credentials" });
    await renderAuthGate();
    expect(screen.getByText("Invalid credentials")).toBeInTheDocument();
  });

  it("shows loading state when isLoading is true", async () => {
    useAuthStore.setState({ isLoading: true });
    await renderAuthGate();
    expect(screen.getByText("...")).toBeInTheDocument();
  });

  it("renders children when user is logged in", async () => {
    useAuthStore.setState({
      user: { id: "u1", email: "a@b.com", display_name: "A" },
      token: "tok",
    });
    await renderAuthGate();
    expect(screen.getByTestId("child-content")).toBeInTheDocument();
    expect(screen.queryByText("Sign In")).not.toBeInTheDocument();
  });
});
