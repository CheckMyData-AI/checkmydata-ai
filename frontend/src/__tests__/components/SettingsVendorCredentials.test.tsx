/**
 * T14 gap 1 — the vendor-credentials panel must be reachable.
 *
 * `VendorCredentialsPanel` was built and unit-tested (SCN-114 / SCN-116) but mounted
 * nowhere, so the only way to add a GA4 service account was the inline "＋ New
 * credential" affordance inside the GA4 connection form, and there was no way at all
 * to *review* or *delete* one afterwards. A tested component that no route renders is
 * not a shipped feature.
 *
 * These tests pin the MOUNT POINT rather than the component's own behaviour (that
 * lives in `VendorCredentialsPanel.test.tsx`). The mount point moved on 2026-09-08:
 * it was a collapsible section in the left rail's Setup group, and it is now a
 * Credentials section in Settings, next to SSH keys — because both belong to the
 * ACCOUNT rather than to any one project, and because they were two of the thirteen
 * collapsible sections that made the rail unreadable (SCN-149).
 *
 * The test followed its subject rather than being deleted with it. A mount-point test
 * whose mount point moves is the one test you must not drop: it is the only thing
 * standing between "we moved it" and "we lost it".
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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

describe("Settings → Credentials", () => {
  it("mounts the panel under a Credentials section", async () => {
    await renderSettings();

    await waitFor(() => {
      expect(screen.getByText("Credentials")).toBeInTheDocument();
    });
    // Next to SSH keys, which is the thing it mirrors — both are account-scoped.
    expect(screen.getByText("SSH keys")).toBeInTheDocument();
    expect(screen.getByText("Vendor credentials")).toBeInTheDocument();
  });

  it("renders the panel's live data from Settings", async () => {
    await renderSettings();

    await waitFor(() => expect(vendorCredentials.list).toHaveBeenCalled());
    expect(await screen.findByText("ga4-service-account")).toBeInTheDocument();
    expect(screen.getByText("collector@example.iam.gserviceaccount.com")).toBeInTheDocument();
  });

  it("surfaces a load failure instead of rendering an empty section", async () => {
    (vendorCredentials.list as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("credential store unreachable"),
    );

    await renderSettings();

    expect(await screen.findByText("credential store unreachable")).toBeInTheDocument();
  });
});

describe("api barrel", () => {
  it("exposes vendorCredentials like every other client", async () => {
    const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");

    expect(typeof actual.api.vendorCredentials.list).toBe("function");
    expect(typeof actual.api.vendorCredentials.create).toBe("function");
    expect(typeof actual.api.vendorCredentials.delete).toBe("function");
    expect(typeof actual.vendorCredentials.list).toBe("function");
  });
});
