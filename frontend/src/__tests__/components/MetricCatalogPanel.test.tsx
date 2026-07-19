import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  MetricCatalogPanel,
  type CatalogMetric,
} from "@/components/insights/MetricCatalogPanel";

function makeMetric(overrides: Partial<CatalogMetric> = {}): CatalogMetric {
  return {
    id: "m1",
    name: "revenue",
    display_name: "Revenue",
    description: "Total revenue",
    category: "revenue",
    source_table: "orders",
    source_column: "amount",
    aggregation: "sum",
    formula: "",
    unit: "USD",
    data_type: "number",
    confidence: 0.9,
    connection_id: null,
    discovery_source: "llm",
    times_referenced: 0,
    ...overrides,
  };
}

describe("MetricCatalogPanel", () => {
  it("shows the empty state when there are no metrics and no error", () => {
    render(<MetricCatalogPanel metrics={[]} />);
    expect(screen.getByText("No metrics found")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("renders an error + Retry distinct from the empty state (SCN-067)", () => {
    const onRetry = vi.fn();
    render(
      <MetricCatalogPanel metrics={[]} error="Failed to load metrics" onRetry={onRetry} />,
    );
    // Error copy is shown and the misleading "No metrics found" empty state is not.
    expect(screen.getByText("Failed to load metrics")).toBeInTheDocument();
    expect(screen.queryByText("No metrics found")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("lists metrics when present", () => {
    render(<MetricCatalogPanel metrics={[makeMetric()]} />);
    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(screen.queryByText("No metrics found")).toBeNull();
  });
});
