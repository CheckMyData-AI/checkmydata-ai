import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useAppStore } from "@/stores/app-store";
import type { ChatSession } from "@/lib/api";

vi.mock("@/stores/app-store", () => {
  const setState = vi.fn();
  const getState = vi.fn().mockReturnValue({
    activeSession: null,
    chatSessions: [],
    hasSessionCache: vi.fn().mockReturnValue(false),
    addSessionMessage: vi.fn(),
  });
  return {
    useAppStore: Object.assign(vi.fn(), { setState, getState }),
  };
});

vi.mock("@/lib/api", () => ({
  api: {
    chat: {
      getMessages: vi.fn().mockResolvedValue([]),
      deleteSession: vi.fn().mockResolvedValue({ ok: true }),
      createSession: vi.fn().mockResolvedValue({
        id: "new-session-id",
        project_id: "proj1",
        title: "New Chat",
        connection_id: null,
      }),
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

const { api } = await import("@/lib/api");

const mockedUseAppStore = useAppStore as unknown as ReturnType<typeof vi.fn> & { setState: ReturnType<typeof vi.fn>; getState: ReturnType<typeof vi.fn> };

function makeSessions(count: number): ChatSession[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `s${i + 1}`,
    project_id: "proj1",
    title: `Session ${i + 1}`,
    connection_id: null,
    status: "idle" as const,
    created_at: new Date().toISOString(),
  }));
}

function setupStore(overrides: Record<string, unknown> = {}) {
  const base = {
    activeProject: { id: "proj1", name: "Test" },
    activeConnection: { id: "conn1", name: "DB" },
    connections: [],
    chatSessions: makeSessions(3),
    activeSession: null,
    setActiveSession: vi.fn(),
    setActiveConnection: vi.fn(),
    setSessionMessages: vi.fn(),
    setChatSessions: vi.fn(),
    ...overrides,
  };
  mockedUseAppStore.mockImplementation((selector?: (s: typeof base) => unknown) =>
    selector ? selector(base) : base,
  );
  mockedUseAppStore.getState.mockReturnValue({
    activeSession: base.activeSession,
    chatSessions: base.chatSessions,
    hasSessionCache: vi.fn().mockReturnValue(false),
    addSessionMessage: vi.fn(),
  });
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

  it("creates a new session via API when createRequested prop is set", async () => {
    const store = setupStore();
    const onHandled = vi.fn();
    render(<ChatSessionList createRequested={true} onCreateHandled={onHandled} />);

    await waitFor(() => {
      expect(api.chat.createSession).toHaveBeenCalledWith({
        project_id: "proj1",
        connection_id: "conn1",
      });
    });
    expect(onHandled).toHaveBeenCalled();
    expect(store.setActiveSession).toHaveBeenCalled();
  });

  it("active session has visual indicator", () => {
    const sessions = makeSessions(3);
    setupStore({ activeSession: sessions[1] });
    render(<ChatSessionList />);

    const activeRow = screen.getByText("Session 2").closest("[role='button']");
    expect(activeRow).toHaveClass("bg-surface-1");
  });

  it("does not trigger new chat when createRequested is false", () => {
    setupStore();
    render(<ChatSessionList createRequested={false} />);
    expect(api.chat.createSession).not.toHaveBeenCalled();
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

  it("skips fetch when session messages are cached", async () => {
    const store = setupStore();
    mockedUseAppStore.getState.mockReturnValue({
      activeSession: null,
      chatSessions: store.chatSessions,
      hasSessionCache: vi.fn().mockReturnValue(true),
      addSessionMessage: vi.fn(),
    });

    render(<ChatSessionList />);
    await userEvent.click(screen.getByText("Session 1"));

    expect(store.setActiveSession).toHaveBeenCalled();
    expect(api.chat.getMessages).not.toHaveBeenCalled();
  });

  it("fetches messages on cache miss and calls setSessionMessages", async () => {
    const store = setupStore();
    mockedUseAppStore.getState.mockReturnValue({
      activeSession: null,
      chatSessions: store.chatSessions,
      hasSessionCache: vi.fn().mockReturnValue(false),
      addSessionMessage: vi.fn(),
    });

    render(<ChatSessionList />);
    await userEvent.click(screen.getByText("Session 1"));

    await waitFor(() => {
      expect(api.chat.getMessages).toHaveBeenCalledWith("s1");
    });
    expect(store.setSessionMessages).toHaveBeenCalledWith("s1", []);
  });

  it("deletes session and removes from chatSessions", async () => {
    const sessions = makeSessions(3);
    const store = setupStore({ activeSession: sessions[0] });
    mockedUseAppStore.getState.mockReturnValue({
      activeSession: sessions[0],
      chatSessions: sessions,
      hasSessionCache: vi.fn().mockReturnValue(false),
      addSessionMessage: vi.fn(),
      messagesBySession: { s1: [], s2: [] },
    });

    render(<ChatSessionList />);
    const deleteBtns = screen.getAllByTestId("action-btn");
    await userEvent.click(deleteBtns[0]);

    await waitFor(() => {
      expect(api.chat.deleteSession).toHaveBeenCalledWith("s1");
    });
    expect(store.setChatSessions).toHaveBeenCalled();
    expect(store.setActiveSession).toHaveBeenCalledWith(null);
    expect(mockedUseAppStore.setState).toHaveBeenCalled();
  });

  it("shows spinner icon for processing sessions", () => {
    const sessions = makeSessions(3);
    sessions[1].status = "processing";
    setupStore({ chatSessions: sessions });
    render(<ChatSessionList />);

    const spinners = document.querySelectorAll(".animate-spin");
    expect(spinners.length).toBe(1);
  });

  it("shows message-square icon for idle sessions", () => {
    const sessions = makeSessions(2);
    setupStore({ chatSessions: sessions });
    render(<ChatSessionList />);

    const spinners = document.querySelectorAll(".animate-spin");
    expect(spinners.length).toBe(0);
    expect(screen.getAllByTestId("icon-message-square")).toHaveLength(2);
  });

  it("delete of non-active session does not clear activeSession", async () => {
    const sessions = makeSessions(3);
    const store = setupStore({ activeSession: sessions[0] });
    mockedUseAppStore.getState.mockReturnValue({
      activeSession: sessions[0],
      chatSessions: sessions,
      hasSessionCache: vi.fn().mockReturnValue(false),
      addSessionMessage: vi.fn(),
      messagesBySession: { s2: [] },
    });

    render(<ChatSessionList />);
    const deleteBtns = screen.getAllByTestId("action-btn");
    await userEvent.click(deleteBtns[1]);

    await waitFor(() => {
      expect(api.chat.deleteSession).toHaveBeenCalledWith("s2");
    });
    expect(store.setChatSessions).toHaveBeenCalled();
    expect(store.setActiveSession).not.toHaveBeenCalledWith(null);
  });
});
