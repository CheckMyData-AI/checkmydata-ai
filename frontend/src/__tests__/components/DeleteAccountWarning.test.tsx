/**
 * SCN-010 — both account-deletion forms name the consequence.
 *
 * The form exists twice (Account menu and Settings), each a local `DeleteConfirm`, and
 * the 2026-09-23 re-audit found the Settings copy had lost "This action cannot be
 * undone" while the Account-menu copy kept it. Two copies drift; this pins the promise
 * on both rather than on the one somebody happened to look at.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useAppStore } from "@/stores/app-store";
import { useAuthStore } from "@/stores/auth-store";

const CREDENTIAL = {
  id: "vc-1",
  name: "ga4-service-account",
  provider: "ga4",
  fingerprint: "abc123def4567890",
  meta: { client_email: "collector@example.iam.gserviceaccount.com" },
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

vi.mock("@/lib/api", () => ({
  api: {
    sshKeys: { list: vi.fn().mockResolvedValue([]) },
    usage: { stats: vi.fn().mockResolvedValue(null) },
    billing: { subscription: vi.fn().mockResolvedValue(null), plans: vi.fn().mockResolvedValue([]) },
    mcpTokens: { list: vi.fn().mockResolvedValue([]) },
  },
}));

vi.mock("@/lib/api/vendor-credentials", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/vendor-credentials")>(
    "@/lib/api/vendor-credentials",
  );
  return {
    ...actual,
    vendorCredentials: {
      list: vi.fn().mockResolvedValue([CREDENTIAL]),
      create: vi.fn(),
      delete: vi.fn(),
    },
  };
});

vi.mock("@/stores/toast-store", () => ({ toast: vi.fn() }));
vi.mock("@/components/ui/ConfirmModal", () => ({
  confirmAction: vi.fn().mockResolvedValue(true),
}));
vi.mock("@/components/ui/Spinner", () => ({ Spinner: () => <div data-testid="spinner" /> }));
vi.mock("@/components/ui/Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));
vi.mock("@/components/ui/ActionButton", () => ({
  ActionButton: ({ icon, title, onClick }: { icon: string; title: string; onClick: () => void }) => (
    <button data-testid={`action-${icon}`} title={title} onClick={onClick}>
      {icon}
    </button>
  ),
}));
vi.mock("@/components/mcp/McpTokenManager", () => ({
  McpTokenManager: () => <div data-testid="mcp-tokens" />,
}));
vi.mock("@/components/usage/UsageStatsPanel", () => ({
  UsageStatsPanel: () => <div data-testid="usage-stats" />,
}));
vi.mock("@/components/billing/BillingPanel", () => ({
  BillingPanel: () => <div data-testid="billing-panel" />,
}));
vi.mock("@/components/analytics/FeedbackAnalyticsPanel", () => ({
  FeedbackAnalyticsPanel: () => <div data-testid="feedback-analytics" />,
}));
vi.mock("@/components/projects/InviteManager", () => ({
  InviteManager: () => <div data-testid="invite-manager" />,
}));

const { vendorCredentials } = await import("@/lib/api/vendor-credentials");

beforeEach(() => {
  vi.clearAllMocks();
  (vendorCredentials.list as ReturnType<typeof vi.fn>).mockResolvedValue([CREDENTIAL]);
  localStorage.clear();
  useAppStore.setState({
    sshKeys: [],
    projects: [],
    activeProject: null,
    connections: [],
    activeConnection: null,
    userRole: null,
  });
  useAuthStore.setState({
    user: { id: "u1", email: "user@test.com", display_name: "Test User" },
    token: "tok",
    isLoading: false,
    error: null,
  });
});

async function renderSettings() {
  const { SettingsPanel } = await import("@/components/settings/SettingsPanel");
  return render(<SettingsPanel onClose={vi.fn()} />);
}

describe("Delete account (SCN-010)", () => {
  it("the Settings form says the deletion cannot be undone", async () => {
    await renderSettings();
    await userEvent.click(await screen.findByText("Delete Account"));
    expect(await screen.findByText(/cannot be undone/i)).toBeInTheDocument();
  });

  it("the Account-menu form says the same", async () => {
    const { AccountMenu } = await import("@/components/auth/AccountMenu");
    render(<AccountMenu />);
    await userEvent.click(screen.getByRole("button", { name: /account/i }));
    await userEvent.click(await screen.findByText(/delete account/i));
    expect(await screen.findByText(/cannot be undone/i)).toBeInTheDocument();
  });
});
