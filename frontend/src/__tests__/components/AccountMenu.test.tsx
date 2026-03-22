import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const logout = vi.fn();

let authState: {
  user: { email: string; auth_provider?: string } | null;
  logout: () => void;
} = {
  user: { email: "test@test.com", auth_provider: "email" },
  logout,
};

vi.mock("@/stores/auth-store", () => ({
  useAuthStore: () => authState,
}));

vi.mock("@/components/ui/Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    auth: {
      changePassword: vi.fn().mockResolvedValue(undefined),
      deleteAccount: vi.fn().mockResolvedValue(undefined),
    },
  },
}));

async function renderMenu() {
  const { AccountMenu } = await import("@/components/auth/AccountMenu");
  return render(<AccountMenu />);
}

beforeEach(() => {
  vi.clearAllMocks();
  authState = {
    user: { email: "test@test.com", auth_provider: "email" },
    logout,
  };
});

describe("AccountMenu", () => {
  it("renders gear button", async () => {
    await renderMenu();
    expect(screen.getByRole("button", { name: "Account settings" })).toBeInTheDocument();
    expect(screen.getByTestId("icon-settings")).toBeInTheDocument();
  });

  it("opens menu on click", async () => {
    const user = userEvent.setup();
    await renderMenu();
    await user.click(screen.getByRole("button", { name: "Account settings" }));
    expect(screen.getByText("Sign Out")).toBeInTheDocument();
    expect(screen.getByText("Delete Account")).toBeInTheDocument();
  });

  it("shows Change Password for email users", async () => {
    const user = userEvent.setup();
    await renderMenu();
    await user.click(screen.getByRole("button", { name: "Account settings" }));
    expect(screen.getByText("Change Password")).toBeInTheDocument();
  });

  it("hides Change Password for Google-only users", async () => {
    const user = userEvent.setup();
    authState = {
      user: { email: "g@test.com", auth_provider: "google" },
      logout,
    };
    await renderMenu();
    await user.click(screen.getByRole("button", { name: "Account settings" }));
    expect(screen.queryByText("Change Password")).not.toBeInTheDocument();
    expect(screen.getByText("Sign Out")).toBeInTheDocument();
  });

  it("Sign Out calls logout", async () => {
    const user = userEvent.setup();
    await renderMenu();
    await user.click(screen.getByRole("button", { name: "Account settings" }));
    await user.click(screen.getByText("Sign Out"));
    expect(logout).toHaveBeenCalledTimes(1);
  });
});
