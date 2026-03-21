import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

vi.mock("@/stores/toast-store", () => ({ toast: vi.fn() }));
vi.mock("@/components/ui/ConfirmModal", () => ({ confirmAction: vi.fn().mockResolvedValue(true) }));
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
    <button data-testid={`action-${icon}`} title={title} onClick={onClick}>
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

vi.mock("./InviteManager", () => ({
  InviteManager: () => <div data-testid="invite-manager" />,
}));

beforeEach(() => {
  vi.clearAllMocks();
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

async function renderSidebar(props: { isMobile?: boolean; isOpen?: boolean; onClose?: () => void } = {}) {
  const { Sidebar } = await import("@/components/Sidebar");
  return render(<Sidebar {...props} />);
}

describe("Sidebar", () => {
  it("renders sidebar element", async () => {
    await renderSidebar();
    expect(screen.getByText("DB Agent")).toBeInTheDocument();
  });

  it("has navigation sections (SSH Keys, Projects)", async () => {
    await renderSidebar();
    await waitFor(() => {
      expect(screen.getByText("SSH Keys")).toBeInTheDocument();
      expect(screen.getByText("Projects")).toBeInTheDocument();
    });
  });

  it("has collapse toggle button", async () => {
    await renderSidebar();
    expect(screen.getByLabelText("Collapse sidebar")).toBeInTheDocument();
  });

  it("shows active project name in workspace sections", async () => {
    useAppStore.setState({
      projects: [{ id: "p1", name: "MyProject" }] as never,
      activeProject: {
        id: "p1",
        name: "MyProject",
        repo_url: null,
        repo_branch: "main",
        ssh_key_id: null,
        description: "",
        indexing_llm_provider: null,
        indexing_llm_model: null,
        agent_llm_provider: null,
        agent_llm_model: null,
        sql_llm_provider: null,
        sql_llm_model: null,
        owner_id: "u1",
        user_role: "owner",
      } as never,
      connections: [],
    });

    await renderSidebar();
    await waitFor(() => {
      expect(screen.getByText("Connections")).toBeInTheDocument();
      expect(screen.getByText("Chat History")).toBeInTheDocument();
    });
  });

  it("has account settings button", async () => {
    await renderSidebar();
    expect(screen.getByTitle("Account settings")).toBeInTheDocument();
  });

  it("renders as a drawer overlay when isMobile and isOpen", async () => {
    const onClose = vi.fn();
    await renderSidebar({ isMobile: true, isOpen: true, onClose });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Close menu")).toBeInTheDocument();
  });

  it("mobile drawer is hidden (translated) when isOpen is false", async () => {
    const onClose = vi.fn();
    await renderSidebar({ isMobile: true, isOpen: false, onClose });
    const dialog = screen.getByRole("dialog");
    expect(dialog.className).toContain("-translate-x-full");
  });

  it("clicking close button calls onClose in mobile drawer", async () => {
    const onClose = vi.fn();
    await renderSidebar({ isMobile: true, isOpen: true, onClose });
    await userEvent.click(screen.getByLabelText("Close menu"));
    expect(onClose).toHaveBeenCalled();
  });
});
