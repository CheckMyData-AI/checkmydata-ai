import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ChatMessage as ChatMessageType } from "@/stores/app-store";

vi.mock("@/lib/api", () => ({
  api: {
    chat: {
      submitFeedback: vi.fn().mockResolvedValue({ ok: true }),
    },
    viz: {
      render: vi.fn(),
      export: vi.fn(),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

vi.mock("@/components/viz/VizRenderer", () => ({
  VizRenderer: ({ data }: { data: Record<string, unknown> }) => (
    <div data-testid="viz-renderer">{JSON.stringify(data)}</div>
  ),
}));

vi.mock("@/components/viz/VizToolbar", () => ({
  VizToolbar: () => <div data-testid="viz-toolbar" />,
}));

vi.mock("@/components/viz/DataTable", () => ({
  DataTable: ({ data }: { data: Record<string, unknown> }) => (
    <div data-testid="data-table">{JSON.stringify(data)}</div>
  ),
}));

vi.mock("@/lib/viz-utils", () => ({
  rerenderViz: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

function makeMessage(overrides: Partial<ChatMessageType> = {}): ChatMessageType {
  return {
    id: "msg1",
    role: "assistant",
    content: "Hello world",
    timestamp: Date.now(),
    ...overrides,
  };
}

async function renderMessage(
  msgOverrides: Partial<ChatMessageType> = {},
  metadataJson?: string | null,
  onRetry?: () => void,
) {
  const { ChatMessage } = await import("@/components/chat/ChatMessage");
  const msg = makeMessage(msgOverrides);
  return render(
    <ChatMessage message={msg} metadataJson={metadataJson} onRetry={onRetry} />,
  );
}

describe("ChatMessage", () => {
  it("renders user message with content", async () => {
    await renderMessage({ role: "user", content: "How many users?" });
    expect(screen.getByText("How many users?")).toBeInTheDocument();
  });

  it("renders assistant message with content", async () => {
    await renderMessage({ role: "assistant", content: "There are 42 users." });
    expect(screen.getByText("There are 42 users.")).toBeInTheDocument();
  });

  it("shows feedback buttons (thumbs up/down) for assistant", async () => {
    await renderMessage({ role: "assistant", content: "Answer" });
    expect(screen.getByTitle("Helpful")).toBeInTheDocument();
    expect(screen.getByTitle("Not helpful")).toBeInTheDocument();
  });

  it("no feedback buttons for user messages", async () => {
    await renderMessage({ role: "user", content: "Question" });
    expect(screen.queryByTitle("Helpful")).not.toBeInTheDocument();
    expect(screen.queryByTitle("Not helpful")).not.toBeInTheDocument();
  });

  it("shows SQL query block when present", async () => {
    await renderMessage({
      role: "assistant",
      content: "Result",
      query: "SELECT * FROM users",
      responseType: "sql_result",
    });
    expect(screen.getByText("View SQL Query")).toBeInTheDocument();
    await userEvent.click(screen.getByText("View SQL Query"));
    expect(screen.getByText("SELECT * FROM users")).toBeInTheDocument();
  });

  it("shows visualization when viz data present", async () => {
    await renderMessage({
      role: "assistant",
      content: "Chart result",
      visualization: {
        type: "chart",
        data: { type: "bar", labels: ["a"], datasets: [] },
      },
      responseType: "sql_result",
      rawResult: { columns: ["x"], rows: [[1]], total_rows: 1 },
    });
    expect(screen.getByTestId("viz-renderer")).toBeInTheDocument();
  });

  it("error displayed with retry button", async () => {
    const onRetry = vi.fn();
    await renderMessage(
      {
        role: "assistant",
        content: "Something failed",
        error: "timeout",
        responseType: "error",
      },
      null,
      onRetry,
    );
    expect(screen.getByText("Error: timeout")).toBeInTheDocument();
    expect(screen.getByText("Retry")).toBeInTheDocument();
  });

  it("markdown content rendered", async () => {
    await renderMessage({
      role: "assistant",
      content: "**bold text** and *italic*",
    });
    const boldEl = screen.getByText("bold text");
    expect(boldEl.tagName).toBe("STRONG");
  });

  it("shows Visual/Text toggle for sql_result with visualization", async () => {
    await renderMessage({
      role: "assistant",
      content: "Here is the chart",
      visualization: {
        type: "chart",
        data: { type: "bar", labels: ["a"], datasets: [{ data: [1] }] },
      },
      responseType: "sql_result",
      rawResult: { columns: ["x"], rows: [[1]], total_rows: 1 },
    });
    expect(screen.getByText("Visual")).toBeInTheDocument();
    expect(screen.getByText("Text")).toBeInTheDocument();
  });

  it("defaults to Visual mode and shows viz-renderer", async () => {
    await renderMessage({
      role: "assistant",
      content: "Chart result",
      visualization: {
        type: "chart",
        data: { type: "bar", labels: ["a"], datasets: [{ data: [1] }] },
      },
      responseType: "sql_result",
      rawResult: { columns: ["x"], rows: [[1]], total_rows: 1 },
    });
    expect(screen.getByTestId("viz-renderer")).toBeInTheDocument();
    expect(screen.queryByTestId("data-table")).not.toBeInTheDocument();
  });

  it("switches to Text mode and shows DataTable instead of chart", async () => {
    await renderMessage({
      role: "assistant",
      content: "Chart result",
      visualization: {
        type: "chart",
        data: { type: "bar", labels: ["a"], datasets: [{ data: [1] }] },
      },
      responseType: "sql_result",
      rawResult: { columns: ["name", "count"], rows: [["Alice", 10]], total_rows: 1 },
    });

    await userEvent.click(screen.getByText("Text"));
    expect(screen.queryByTestId("viz-renderer")).not.toBeInTheDocument();
    expect(screen.getByTestId("data-table")).toBeInTheDocument();
  });

  it("Text mode shows nothing if no rawResult", async () => {
    await renderMessage({
      role: "assistant",
      content: "Chart result",
      visualization: {
        type: "chart",
        data: { type: "bar", labels: ["a"], datasets: [{ data: [1] }] },
      },
      responseType: "sql_result",
    });

    await userEvent.click(screen.getByText("Text"));
    expect(screen.queryByTestId("viz-renderer")).not.toBeInTheDocument();
    expect(screen.queryByTestId("data-table")).not.toBeInTheDocument();
  });
});
