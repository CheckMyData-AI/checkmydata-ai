import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useAppStore } from "@/stores/app-store";
import type { ChatSession } from "@/lib/api";

vi.mock("@/stores/app-store", () => ({
  useAppStore: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    chat: {
      getMessages: vi.fn().mockResolvedValue([]),
      deleteSession: vi.fn().mockResolvedValue({ ok: true }),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

vi.mock("@/components/ui/ConfirmModal", () => ({
  confirmAction: vi.fn().mockResolvedValue(true),
}));

vi.mock("@/components/ui/Icon", () => ({
  Icon: (p: any) => <span data-testid={`icon-${p.name}`} />,
}));

vi.mock("@/components/ui/ActionButton", () => ({
  ActionButton: (p: any) => (
    <button data-testid="action-btn" onClick={p.onClick}>
      {p.title}
    </button>
  ),
}));

const { ChatSessionList } = await import(
  "@/components/chat/ChatSessionList"
);

const mockedUseAppStore = useAppStore as unknown as ReturnType<typeof vi.fn>;

function makeSessions(count: number): ChatSession[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `s${i + 1}`,
    project_id: "proj1",
    title: `Session ${i + 1}`,
    connection_id: null,
    created_at: new Date().toISOString(),
  }));
}

function setupStore(overrides: Record<string, unknown> = {}) {
  const base = {
    activeProject: { id: "proj1", name: "Test" },
    connections: [],
    chatSessions: makeSessions(3),
    activeSession: null,
    setActiveSession: vi.fn(),
    setActiveConnection: vi.fn(),
    setMessages: vi.fn(),
    setChatSessions: vi.fn(),
    ...overrides,
  };
  mockedUseAppStore.mockReturnValue(base);
  return base;
}

describe("ChatSessionList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns null when no activeProject", () => {
    setupStore({ activeProject: null });
    const { container } = render(<ChatSessionList />);
    expect(container.innerHTML).toBe("");
  });

  it("shows empty state when chatSessions is empty", () => {
    setupStore({ chatSessions: [] });
    render(<ChatSessionList />);
    expect(screen.getByText("No chats yet")).toBeInTheDocument();
  });

  it("renders session titles", () => {
    setupStore();
    render(<ChatSessionList />);
    expect(screen.getByText("Session 1")).toBeInTheDocument();
    expect(screen.getByText("Session 2")).toBeInTheDocument();
    expect(screen.getByText("Session 3")).toBeInTheDocument();
  });

  it('shows "New Chat" button', () => {
    setupStore();
    render(<ChatSessionList />);
    expect(screen.getByText("New Chat")).toBeInTheDocument();
  });

  it("active session has visual indicator", () => {
    const sessions = makeSessions(3);
    setupStore({ activeSession: sessions[1] });
    render(<ChatSessionList />);

    const activeRow = screen.getByText("Session 2").closest("[role='button']");
    expect(activeRow).toHaveClass("bg-surface-1");
  });

  it("clicking New Chat resets active session and messages", async () => {
    const store = setupStore();
    render(<ChatSessionList />);

    await userEvent.click(screen.getByText("New Chat"));
    expect(store.setActiveSession).toHaveBeenCalledWith(null);
    expect(store.setMessages).toHaveBeenCalledWith([]);
  });

  it('shows "Show all" button when > 5 sessions', () => {
    setupStore({ chatSessions: makeSessions(8) });
    render(<ChatSessionList />);

    expect(screen.getByText(/Show all 8/)).toBeInTheDocument();
    expect(screen.queryByText("Session 6")).not.toBeInTheDocument();
  });

  it("clicking Show all reveals hidden sessions", async () => {
    setupStore({ chatSessions: makeSessions(8) });
    render(<ChatSessionList />);

    await userEvent.click(screen.getByText(/Show all 8/));
    expect(screen.getByText("Session 6")).toBeInTheDocument();
    expect(screen.getByText("Session 8")).toBeInTheDocument();
  });

  it("does not show Show all when <= 5 sessions", () => {
    setupStore({ chatSessions: makeSessions(4) });
    render(<ChatSessionList />);
    expect(screen.queryByText(/Show all/)).not.toBeInTheDocument();
  });
});
