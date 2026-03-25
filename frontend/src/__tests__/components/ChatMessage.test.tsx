import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ChatMessage as ChatMessageType } from "@/stores/app-store";

vi.mock("@/lib/api", () => ({
  api: {
    chat: {
      submitFeedback: vi.fn().mockResolvedValue({ ok: true }),
      summarize: vi.fn().mockResolvedValue({ summary: "Test summary", message_id: "msg1" }),
    },
    viz: {
      render: vi.fn(),
      export: vi.fn(),
    },
    dataValidation: {
      validateData: vi.fn().mockResolvedValue({ ok: true }),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

vi.mock("@/stores/app-store", () => {
  const state = {
    activeProject: { id: "proj1", name: "Test Project" },
    activeConnection: { id: "conn1" },
  };
  const useAppStore = Object.assign(
    () => state,
    { getState: () => state },
  );
  return { useAppStore };
});

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

vi.mock("react-markdown", () => ({
  __esModule: true,
  default: ({ children, components }: { children: string; components?: Record<string, unknown> }) => {
    const P = (components?.p as React.FC<{ children: React.ReactNode }>) || (({ children: c }: { children: React.ReactNode }) => <p>{c}</p>);
    return <P>{children}</P>;
  },
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
  onSendMessage?: (text: string) => void,
  sessionId?: string,
) {
  const { ChatMessage } = await import("@/components/chat/ChatMessage");
  const msg = makeMessage(msgOverrides);
  return render(
    <ChatMessage message={msg} metadataJson={metadataJson} onRetry={onRetry} onSendMessage={onSendMessage} sessionId={sessionId} />,
  );
}

describe("ChatMessage", () => {
  it("renders user message with content", async () => {
    await renderMessage({ role: "user", content: "How many users?" });
    expect(screen.getByText("How many users?")).toBeInTheDocument();
  });

  it("renders assistant message with content", async () => {
    await renderMessage({ role: "assistant", content: "There are 42 users." });
    expect(await screen.findByText("There are 42 users.")).toBeInTheDocument();
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
    expect(screen.getByText("**bold text** and *italic*")).toBeInTheDocument();
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

  it("renders insight cards when metadata has insights", async () => {
    const meta = JSON.stringify({
      response_type: "sql_result",
      insights: [
        { type: "trend_up", title: "Upward trend in revenue", description: "Revenue increased by 25%", confidence: 0.8 },
        { type: "outlier", title: "Outlier in sales", description: "Row 3 is 3x the average", confidence: 0.7 },
      ],
    });

    await renderMessage(
      { role: "assistant", content: "Result", query: "SELECT 1", responseType: "sql_result" },
      meta,
      undefined,
      vi.fn(),
    );

    expect(screen.getByText("Upward trend in revenue")).toBeInTheDocument();
    expect(screen.getByText("Outlier in sales")).toBeInTheDocument();
  });

  it("does not render insight cards when insights array is empty", async () => {
    const meta = JSON.stringify({
      response_type: "sql_result",
      insights: [],
    });

    await renderMessage(
      { role: "assistant", content: "Result", query: "SELECT 1", responseType: "sql_result" },
      meta,
    );

    expect(screen.queryByText("Drill down")).not.toBeInTheDocument();
  });

  it("shows Summary button for sql_result messages", async () => {
    await renderMessage({
      role: "assistant",
      content: "Result",
      query: "SELECT * FROM users",
      responseType: "sql_result",
    });

    expect(screen.getByText("Summary")).toBeInTheDocument();
  });

  it("shows 'Tap to view chart' button for mobile-collapsed viz", async () => {
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

    expect(screen.getByText("Tap to view chart")).toBeInTheDocument();
  });

  it("uses wider max-width on mobile (95%)", async () => {
    await renderMessage({ role: "assistant", content: "Hello" });
    const outer = screen.getByText("Hello").closest("[class*='max-w-']");
    expect(outer?.className).toContain("max-w-[95%]");
  });

  it("thumbs down on SQL result auto-sends investigation message", async () => {
    const { api } = await import("@/lib/api");
    const onSend = vi.fn();
    await renderMessage(
      { role: "assistant", content: "Result", query: "SELECT 1", responseType: "sql_result" },
      null,
      undefined,
      onSend,
      "session-1",
    );

    const thumbDown = screen.getByTitle("Not helpful");
    await userEvent.click(thumbDown);

    expect(api.chat.submitFeedback).toHaveBeenCalledWith("msg1", -1);
    expect(api.dataValidation.validateData).toHaveBeenCalledWith(
      expect.objectContaining({ verdict: "rejected", message_id: "msg1" }),
    );
    expect(onSend).toHaveBeenCalledWith(
      "I flagged the previous query result as incorrect. Please investigate what might be wrong and suggest a corrected query.",
    );
  });

  it("thumbs up on SQL result records data validation as confirmed", async () => {
    const { api } = await import("@/lib/api");
    const onSend = vi.fn();
    await renderMessage(
      { role: "assistant", content: "Result", query: "SELECT 1", responseType: "sql_result" },
      null,
      undefined,
      onSend,
      "session-1",
    );

    const thumbUp = screen.getByTitle("Helpful");
    await userEvent.click(thumbUp);

    expect(api.chat.submitFeedback).toHaveBeenCalledWith("msg1", 1);
    expect(api.dataValidation.validateData).toHaveBeenCalledWith(
      expect.objectContaining({ verdict: "confirmed", message_id: "msg1" }),
    );
    expect(onSend).not.toHaveBeenCalled();
  });

  it("thumbs down on non-SQL message does not auto-send", async () => {
    const { api } = await import("@/lib/api");
    const onSend = vi.fn();
    await renderMessage(
      { role: "assistant", content: "Just a text response" },
      null,
      undefined,
      onSend,
      "session-1",
    );

    const thumbDown = screen.getByTitle("Not helpful");
    await userEvent.click(thumbDown);

    expect(api.chat.submitFeedback).toHaveBeenCalledWith("msg1", -1);
    expect(api.dataValidation.validateData).not.toHaveBeenCalled();
    expect(onSend).not.toHaveBeenCalled();
  });

  it("renders session_continuation as SessionContinuationBanner", async () => {
    await renderMessage(
      {
        role: "system",
        content: "Session continued (15 earlier messages summarized)",
        responseType: "session_continuation",
      },
      JSON.stringify({
        old_session_id: "old-123",
        summary_preview: "User explored revenue data.",
        topics: ["revenue"],
      }),
    );

    expect(screen.getByText(/15 messages summarized/)).toBeInTheDocument();
  });
});
