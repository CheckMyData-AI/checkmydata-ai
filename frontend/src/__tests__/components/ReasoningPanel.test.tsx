import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { useReasoningStore, type ReasoningStep } from "@/stores/reasoning-store";
import { ReasoningPanel } from "@/components/chat/ReasoningPanel";

function makeStep(overrides: Partial<ReasoningStep> = {}): ReasoningStep {
  return {
    step: "sql:get_schema",
    status: "completed",
    detail: "",
    agent: "sql_agent",
    timestamp: Date.now(),
    ...overrides,
  };
}

beforeEach(() => {
  // jsdom has no matchMedia — stub it for useMobileLayout (desktop layout).
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });

  useReasoningStore.setState({
    panelOpen: true,
    activeMessageId: "m1",
    traces: {
      m1: {
        steps: [
          makeStep({ detail: "Fetch schema", elapsed_ms: 1500 }),
          makeStep({ step: "sql:learnings", detail: "Load learnings", agent: undefined, elapsed_ms: 250 }),
          makeStep({ step: "sql:llm_call", detail: "Generate SQL", agent: "llm" }),
        ],
        planSummary: null,
        thinkingLog: [],
        startTime: 0,
        endTime: 10000,
      },
    },
  });
});

describe("ReasoningPanel per-step elapsed (SCN-054)", () => {
  it("renders each step's duration next to the step", () => {
    render(<ReasoningPanel />);

    expect(screen.getByText("Fetch schema")).toBeInTheDocument();
    expect(screen.getByText("1.5s")).toBeInTheDocument();
    expect(screen.getByText("250ms")).toBeInTheDocument();
  });

  it("omits the duration for steps without elapsed_ms and keeps the header total", () => {
    render(<ReasoningPanel />);

    const generateRow = screen.getByText("Generate SQL").closest("div")
      ?.parentElement as HTMLElement;
    expect(generateRow.textContent).not.toContain("1.5s");
    expect(generateRow.textContent).not.toContain("250ms");
    // Overall elapsed stays in the header.
    expect(screen.getByText("10.0s")).toBeInTheDocument();
  });
});
