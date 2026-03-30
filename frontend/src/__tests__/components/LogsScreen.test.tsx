import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { LogsSummary } from "@/components/logs/LogsSummary";
import { LogsDateFilter } from "@/components/logs/LogsDateFilter";
import { LogsUserFilter } from "@/components/logs/LogsUserFilter";
import type { LogSummary, LogUser } from "@/lib/api";

describe("LogsSummary", () => {
  const summary: LogSummary = {
    total_requests: 150,
    successful: 140,
    failed: 10,
    total_llm_calls: 300,
    total_db_queries: 50,
    avg_duration_ms: 1234.5,
    total_tokens: 50000,
    total_cost_usd: 0.85,
    by_status: { completed: 140, failed: 10 },
    by_type: { sql_result: 80, text: 70 },
  };

  it("renders all KPI cards", () => {
    const { container } = render(<LogsSummary summary={summary} />);
    expect(container.textContent).toContain("150");
    expect(container.textContent).toContain("93.3%");
    expect(container.textContent).toContain("10");
    expect(container.textContent).toContain("300");
    expect(container.textContent).toContain("50");
    expect(container.textContent).toContain("1.2s");
    expect(container.textContent).toContain("$0.85");
  });
});

describe("LogsDateFilter", () => {
  it("renders all options", () => {
    const onChange = vi.fn();
    render(<LogsDateFilter days={7} onChange={onChange} />);
    expect(screen.getByText("7d")).toBeInTheDocument();
    expect(screen.getByText("14d")).toBeInTheDocument();
    expect(screen.getByText("30d")).toBeInTheDocument();
    expect(screen.getByText("90d")).toBeInTheDocument();
  });

  it("calls onChange when clicked", async () => {
    const onChange = vi.fn();
    render(<LogsDateFilter days={7} onChange={onChange} />);
    screen.getByText("30d").click();
    expect(onChange).toHaveBeenCalledWith(30);
  });
});

describe("LogsUserFilter", () => {
  const users: LogUser[] = [
    {
      user_id: "u1",
      display_name: "Alice",
      email: "alice@test.com",
      picture_url: null,
      request_count: 10,
      last_request_at: "2026-03-30T10:00:00Z",
    },
    {
      user_id: "u2",
      display_name: "Bob",
      email: "bob@test.com",
      picture_url: null,
      request_count: 5,
      last_request_at: "2026-03-29T10:00:00Z",
    },
  ];

  it("renders user list with counts", () => {
    render(<LogsUserFilter users={users} selectedUserId={null} onSelect={() => {}} />);
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("shows All users option", () => {
    render(<LogsUserFilter users={users} selectedUserId={null} onSelect={() => {}} />);
    expect(screen.getByText("All users")).toBeInTheDocument();
  });

  it("calls onSelect when user is clicked", () => {
    const onSelect = vi.fn();
    render(<LogsUserFilter users={users} selectedUserId={null} onSelect={onSelect} />);
    screen.getByText("Alice").click();
    expect(onSelect).toHaveBeenCalledWith("u1");
  });
});
