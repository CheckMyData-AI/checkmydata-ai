import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("next/dynamic", () => ({
  default: (_loader: unknown, _opts?: unknown) => ({ config }: { config: Record<string, unknown> }) => (
    <div data-testid="chart-renderer">{String(config.type ?? "")}</div>
  ),
}));

vi.mock("@/components/viz/ChartRenderer", () => ({
  ChartRenderer: ({ config }: { config: Record<string, unknown> }) => (
    <div data-testid="chart-renderer">{String(config.type ?? "")}</div>
  ),
}));

vi.mock("@/components/viz/DataTable", () => ({
  DataTable: () => <div data-testid="data-table">table</div>,
}));

const { default: VizRenderer } = await import("@/components/viz/VizRenderer");

describe("VizRenderer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders DataTable when type is "table"', () => {
    render(<VizRenderer data={{ type: "table", data: { columns: [], rows: [] } }} />);
    expect(screen.getByTestId("data-table")).toBeInTheDocument();
  });

  it('renders ChartRenderer when type is "chart"', () => {
    render(<VizRenderer data={{ type: "chart", data: { type: "bar" } }} />);
    expect(screen.getByTestId("chart-renderer")).toHaveTextContent("bar");
  });

  it('renders text content when type is "text"', () => {
    render(<VizRenderer data={{ type: "text", data: { content: "hello" } }} />);
    expect(screen.getByText("hello")).toBeInTheDocument();
  });

  it('renders a formatted number when type is "number"', () => {
    render(
      <VizRenderer
        data={{ type: "number", data: { type: "number", value: 1234, label: "total" } }}
      />,
    );
    expect(screen.getByText("1234")).toBeInTheDocument();
    expect(screen.getByText("total")).toBeInTheDocument();
  });

  it('renders key-value pairs when type is "key_value"', () => {
    render(
      <VizRenderer
        data={{
          type: "key_value",
          data: { type: "key_value", data: { alpha: "one", beta: "two" } },
        }}
      />,
    );
    expect(screen.getByText("alpha")).toBeInTheDocument();
    expect(screen.getByText("one")).toBeInTheDocument();
    expect(screen.getByText("beta")).toBeInTheDocument();
    expect(screen.getByText("two")).toBeInTheDocument();
  });

  it("falls back to DataTable for an unknown type", () => {
    render(<VizRenderer data={{ type: "unknown", data: {} }} />);
    expect(screen.getByTestId("data-table")).toBeInTheDocument();
  });

  it("defaults to DataTable when type is missing", () => {
    render(<VizRenderer data={{ data: {} } as Record<string, unknown>} />);
    expect(screen.getByTestId("data-table")).toBeInTheDocument();
  });
});
