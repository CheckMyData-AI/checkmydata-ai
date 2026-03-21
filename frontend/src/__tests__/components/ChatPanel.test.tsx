import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useAppStore } from "@/stores/app-store";
import type { Project, Connection } from "@/lib/api";

Element.prototype.scrollIntoView = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    chat: {
      askStream: vi.fn(() => new AbortController()),
      listSessions: vi.fn().mockResolvedValue([]),
      generateTitle: vi.fn().mockResolvedValue({ id: "s1", title: "Title" }),
      suggestions: vi.fn().mockResolvedValue([]),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

vi.mock("@/components/chat/ChatInput", () => ({
  ChatInput: ({
    onSend,
    disabled,
  }: {
    onSend: (v: string) => void;
    disabled: boolean;
  }) => (
    <div data-testid="chat-input">
      <input
        data-testid="chat-input-field"
        aria-label="Chat input"
        disabled={disabled}
        onKeyDown={(e) => {
          if (e.key === "Enter") onSend((e.target as HTMLInputElement).value);
        }}
      />
    </div>
  ),
}));

vi.mock("@/components/chat/ChatMessage", () => ({
  ChatMessage: ({ message }: { message: { role: string; content: string } }) => (
    <div data-testid={`msg-${message.role}`}>{message.content}</div>
  ),
}));

vi.mock("@/components/chat/ToolCallIndicator", () => ({
  ToolCallIndicator: () => <div data-testid="tool-calls" />,
}));

vi.mock("@/components/chat/ThinkingLog", () => ({
  ThinkingLog: ({ entries }: { entries: string[] }) => (
    <div data-testid="thinking-log">{entries.join("; ")}</div>
  ),
}));

vi.mock("@/components/log/LogPanel", () => ({
  LogToggleButton: () => <button data-testid="log-toggle">Logs</button>,
}));

vi.mock("@/components/chat/ReadinessGate", () => ({
  ReadinessGate: ({ onBypass }: { onBypass: () => void }) => (
    <div data-testid="readiness-gate">
      <button onClick={onBypass}>Bypass</button>
    </div>
  ),
  ReadinessBanner: () => <div data-testid="readiness-banner" />,
}));

vi.mock("@/components/chat/SuggestionChips", () => ({
  SuggestionChips: ({
    suggestions,
    onSelect,
  }: {
    suggestions: Array<{ text: string }>;
    loading?: boolean;
    onSelect: (t: string) => void;
  }) =>
    suggestions.length > 0 ? (
      <div data-testid="suggestion-chips">
        {suggestions.map((s: { text: string }, i: number) => (
          <button key={i} data-testid="chip" onClick={() => onSelect(s.text)}>
            {s.text}
          </button>
        ))}
      </div>
    ) : null,
}));

vi.mock("@/lib/sse", () => ({}));

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: "p1",
    name: "Test",
    description: "",
    repo_url: null,
    repo_branch: "main",
    ssh_key_id: null,
    indexing_llm_provider: null,
    indexing_llm_model: null,
    agent_llm_provider: null,
    agent_llm_model: null,
    sql_llm_provider: null,
    sql_llm_model: null,
    owner_id: "u1",
    user_role: "owner",
    ...overrides,
  };
}

function makeConnection(overrides: Partial<Connection> = {}): Connection {
  return {
    id: "c1",
    project_id: "p1",
    name: "TestDB",
    db_type: "postgres",
    source_type: "direct",
    ssh_host: null,
    ssh_port: 22,
    ssh_user: null,
    ssh_key_id: null,
    db_host: "localhost",
    db_port: 5432,
    db_name: "testdb",
    db_user: "admin",
    is_read_only: true,
    is_active: true,
    ssh_exec_mode: false,
    ssh_command_template: null,
    ssh_pre_commands: null,
    mcp_server_command: null,
    mcp_server_url: null,
    mcp_transport_type: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  useAppStore.setState({
    activeProject: null,
    activeConnection: null,
    activeSession: null,
    messages: [],
    isThinking: false,
    chatMode: "full",
    activeToolCalls: [],
    chatSessions: [],
  });
});

async function renderPanel() {
  const { ChatPanel } = await import("@/components/chat/ChatPanel");
  return render(<ChatPanel />);
}

describe("ChatPanel", () => {
  it("renders chat panel with select project prompt when no project", async () => {
    await renderPanel();
    expect(screen.getByText("Select a project to start chatting")).toBeInTheDocument();
  });

  it("shows empty state / welcome message when project and connection set", async () => {
    useAppStore.setState({
      activeProject: makeProject(),
      activeConnection: makeConnection(),
      messages: [],
    });

    await renderPanel();
    // Bypass the readiness gate to see the welcome message
    await userEvent.click(screen.getByText("Bypass"));
    await waitFor(() => {
      expect(screen.getByText("Ready to query")).toBeInTheDocument();
    });
  });

  it("renders user messages", async () => {
    useAppStore.setState({
      activeProject: makeProject(),
      activeConnection: makeConnection(),
      messages: [
        { id: "m1", role: "user", content: "Hello", timestamp: Date.now() },
      ],
    });

    await renderPanel();
    expect(screen.getByTestId("msg-user")).toHaveTextContent("Hello");
  });

  it("renders assistant messages", async () => {
    useAppStore.setState({
      activeProject: makeProject(),
      activeConnection: makeConnection(),
      messages: [
        {
          id: "m2",
          role: "assistant",
          content: "Here is your result",
          timestamp: Date.now(),
        },
      ],
    });

    await renderPanel();
    expect(screen.getByTestId("msg-assistant")).toHaveTextContent(
      "Here is your result",
    );
  });

  it("shows loading indicator during streaming", async () => {
    useAppStore.setState({
      activeProject: makeProject(),
      activeConnection: makeConnection(),
      messages: [
        { id: "m1", role: "user", content: "query", timestamp: Date.now() },
      ],
      isThinking: true,
    });

    await renderPanel();
    const bounceDots = document.querySelectorAll(".animate-bounce");
    expect(bounceDots.length).toBeGreaterThanOrEqual(3);
  });

  it("error message displayed", async () => {
    useAppStore.setState({
      activeProject: makeProject(),
      activeConnection: makeConnection(),
      messages: [
        {
          id: "m1",
          role: "assistant",
          content: "Error: Something went wrong",
          error: "Something went wrong",
          responseType: "error",
          timestamp: Date.now(),
        },
      ],
    });

    await renderPanel();
    expect(screen.getByTestId("msg-assistant")).toHaveTextContent(
      "Error: Something went wrong",
    );
  });

  it("scrolls to bottom on new message (ref exists)", async () => {
    useAppStore.setState({
      activeProject: makeProject(),
      activeConnection: makeConnection(),
      messages: [
        { id: "m0", role: "user", content: "first", timestamp: Date.now() },
      ],
    });

    const { rerender } = await renderPanel();
    expect(screen.getByTestId("msg-user")).toBeInTheDocument();

    useAppStore.setState({
      messages: [
        { id: "m0", role: "user", content: "first", timestamp: Date.now() },
        { id: "m1", role: "assistant", content: "reply", timestamp: Date.now() },
      ],
    });

    const { ChatPanel } = await import("@/components/chat/ChatPanel");
    rerender(<ChatPanel />);

    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it("has input area", async () => {
    useAppStore.setState({
      activeProject: makeProject(),
      activeConnection: makeConnection(),
      messages: [],
    });

    await renderPanel();
    await userEvent.click(screen.getByText("Bypass"));
    await waitFor(() => {
      expect(screen.getByTestId("chat-input")).toBeInTheDocument();
    });
  });

  it("shows suggestion chips when suggestions load for empty session", async () => {
    const { api } = await import("@/lib/api");
    (api.chat.suggestions as ReturnType<typeof vi.fn>).mockResolvedValue([
      { text: "How many orders?", source: "schema", table: "orders" },
      { text: "Show me users", source: "schema", table: "users" },
    ]);

    useAppStore.setState({
      activeProject: makeProject(),
      activeConnection: makeConnection(),
      messages: [],
    });

    await renderPanel();
    await userEvent.click(screen.getByText("Bypass"));
    await waitFor(() => {
      expect(screen.getByTestId("suggestion-chips")).toBeInTheDocument();
    });
    expect(screen.getAllByTestId("chip")).toHaveLength(2);
  });

  it("shows bouncing dots when thinking with no thinking log", async () => {
    useAppStore.setState({
      activeProject: makeProject(),
      activeConnection: makeConnection(),
      messages: [
        { id: "m1", role: "user", content: "query", timestamp: Date.now() },
      ],
      isThinking: true,
    });

    await renderPanel();
    const dots = document.querySelectorAll(".animate-bounce");
    expect(dots.length).toBeGreaterThanOrEqual(3);
    expect(screen.queryByTestId("thinking-log")).not.toBeInTheDocument();
  });
});
