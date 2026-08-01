/**
 * T14 gap 1 — the vendor-credentials panel must be reachable.
 *
 * `VendorCredentialsPanel` was built and unit-tested (SCN-114 / SCN-116) but
 * mounted nowhere, so the only way to add a GA4 service account was the inline
 * "＋ New credential" affordance inside the GA4 connection form — and there was
 * no way at all to *review* or *delete* one afterwards. A tested component that
 * no route renders is not a shipped feature.
 *
 * These tests pin the mount point rather than the component's own behaviour
 * (that lives in `VendorCredentialsPanel.test.tsx`): the section exists in the
 * sidebar's Setup group next to SSH Keys, in the desktop rail *and* the mobile
 * drawer, and the panel it wraps actually renders live data there.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { useAppStore } from "@/stores/app-store";
import { useAuthStore } from "@/stores/auth-store";

vi.mock("@/lib/api", () => ({
  api: {
    sshKeys: { list: vi.fn().mockResolvedValue([]) },
    repos: { status: vi.fn().mockResolvedValue(null), checkUpdates: vi.fn(), index: vi.fn() },
    projects: { list: vi.fn().mockResolvedValue([]) },
    connections: { listByProject: vi.fn().mockResolvedValue([]) },
    chat: { listSessions: vi.fn().mockResolvedValue([]) },
    rules: { list: vi.fn().mockResolvedValue([]) },
    knowledge: { list: vi.fn().mockResolvedValue([]) },
  },
}));

const CREDENTIAL = {
  id: "vc-1",
  name: "ga4-service-account",
  provider: "ga4",
  fingerprint: "abc123def4567890",
  meta: { client_email: "collector@example.iam.gserviceaccount.com" },
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

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

vi.mock("@/components/ui/LlmModelSelector", () => ({
  LlmModelSelector: () => <div data-testid="llm-selector" />,
  formatProvider: (p: string) => p,
  formatModelShort: (m: string) => m,
  EMPTY_LLM: { provider: "", model: "" },
}));

vi.mock("@/components/invites/PendingInvites", () => ({
  PendingInvites: () => <div data-testid="pending-invites" />,
}));

vi.mock("@/components/knowledge/KnowledgeDocs", () => ({
  KnowledgeDocs: () => <div data-testid="knowledge-docs" />,
}));

vi.mock("@/components/knowledge/KnowledgeHub", () => ({
  KnowledgeHub: () => <div data-testid="knowledge-hub" />,
}));

vi.mock("@/hooks/useAppPanel", () => ({
  useAppPanel: () => ({ panel: null, setPanel: vi.fn() }),
}));

vi.mock("@/components/workflow/WorkflowProgress", () => ({
  WorkflowProgress: () => <div data-testid="workflow-progress" />,
}));

vi.mock("@/components/connections/SyncStatusIndicator", () => ({
  SyncStatusIndicator: () => <div data-testid="sync-status" />,
}));

vi.mock("@/components/analytics/FeedbackAnalyticsPanel", () => ({
  FeedbackAnalyticsPanel: () => <div data-testid="feedback-analytics" />,
}));

vi.mock("@/components/schedules/ScheduleManager", () => ({
  ScheduleManager: () => <div data-testid="schedule-manager" />,
}));

vi.mock("@/components/dashboards/DashboardList", () => ({
  DashboardList: () => <div data-testid="dashboard-list" />,
}));

vi.mock("@/components/ui/NotificationBell", () => ({
  NotificationBell: () => <div data-testid="notification-bell" />,
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
    chatSessions: [],
    activeSession: null,
    messages: [],
    isLoading: false,
    userRole: null,
  });
  useAuthStore.setState({
    user: { id: "u1", email: "user@test.com", display_name: "Test User" },
    token: "tok",
    isLoading: false,
    error: null,
  });
});

async function renderSidebar(
  props: { isMobile?: boolean; isOpen?: boolean; onClose?: () => void } = {},
) {
  const { Sidebar } = await import("@/components/Sidebar");
  return render(<Sidebar {...props} />);
}

describe("Sidebar → Vendor Credentials", () => {
  it("mounts the section in the desktop Setup group", async () => {
    await renderSidebar();

    await waitFor(() => {
      expect(screen.getByText("Vendor Credentials")).toBeInTheDocument();
    });
    // Next to SSH Keys, which is the section it mirrors.
    expect(screen.getByText("SSH Keys")).toBeInTheDocument();
  });

  it("renders the panel's live data from the sidebar", async () => {
    await renderSidebar();

    await waitFor(() => expect(vendorCredentials.list).toHaveBeenCalled());
    expect(await screen.findByText("ga4-service-account")).toBeInTheDocument();
    expect(
      screen.getByText("collector@example.iam.gserviceaccount.com"),
    ).toBeInTheDocument();
  });

  it("exposes an accessible, collapsible section header", async () => {
    await renderSidebar();

    const header = await screen.findByRole("button", {
      name: "Vendor Credentials section",
    });
    expect(header).toHaveAttribute("aria-expanded");
  });

  it("mounts the section in the mobile drawer too", async () => {
    await renderSidebar({ isMobile: true, isOpen: true, onClose: vi.fn() });

    const drawer = screen.getByRole("dialog");
    await waitFor(() => {
      expect(within(drawer).getByText("Vendor Credentials")).toBeInTheDocument();
    });
    expect(await within(drawer).findByText("ga4-service-account")).toBeInTheDocument();
  });

  it("surfaces a load failure instead of rendering an empty section", async () => {
    (vendorCredentials.list as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("credential store unreachable"),
    );

    await renderSidebar();

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
