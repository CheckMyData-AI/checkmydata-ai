import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { ChartRenderer } from "@/components/viz/ChartRenderer";

/**
 * The version of this file that came before mocked `react-chartjs-2` and
 * `chart.js` entirely and then asserted that a mock had rendered — so it could
 * not have failed against any defect inside the component. These assert on what
 * reaches the DOM instead.
 *
 * Recharts measures its container, and jsdom reports every element as 0×0, so
 * the responsive wrapper renders nothing without a size. The observer below is
 * the minimum that makes the chart body real in a test.
 */
beforeAll(() => {
  class ResizeObserverStub {
    callback: ResizeObserverCallback;
    constructor(callback: ResizeObserverCallback) {
      this.callback = callback;
    }
    observe(target: Element) {
      this.callback(
        [{ target, contentRect: { width: 640, height: 320 } } as unknown as ResizeObserverEntry],
        this as unknown as ResizeObserver,
      );
    }
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 640 });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, value: 320 });
});

const labels = ["Jan", "Feb", "Mar"];
const datasets = [{ label: "Sales", data: [10, 20, 30] }];

describe("ChartRenderer — the empty and unsupported paths", () => {
  it.each([
    ["data is null", { type: "bar", data: null }],
    ["datasets is empty", { type: "bar", data: { labels, datasets: [] } }],
    ["the only series is empty", { type: "bar", data: { labels, datasets: [{ label: "X", data: [] }] } }],
    ["data is missing", { type: "line" }],
  ])("says so plainly when %s", (_case, config) => {
    render(<ChartRenderer config={config as Record<string, unknown>} />);
    expect(screen.getByText("No chart data available")).toBeInTheDocument();
  });

  it("names an unsupported type and points at the table instead of failing silently", () => {
    render(<ChartRenderer config={{ type: "treemap", data: { labels, datasets } }} />);
    expect(screen.getByText(/Unsupported chart type/)).toBeInTheDocument();
    expect(screen.getByText(/Try Table view/)).toBeInTheDocument();
  });
});

describe("ChartRenderer — the pack's contract", () => {
  it("renders a bar chart whose series colour resolves through the pack's ramp", () => {
    const { container } = render(
      <ChartRenderer config={{ type: "bar", data: { labels, datasets } }} />,
    );
    // shadcn's ChartContainer emits `--color-<key>` from the config; the value
    // must be a token, never a literal, or the chart stops following the theme.
    const style = container.querySelector("style")?.textContent ?? "";
    expect(style).toContain("--color-s0: var(--chart-1)");
    expect(style).not.toMatch(/#[0-9a-f]{6}|rgba?\(/i);

    // The ChartConfig is only half of it — a `fill` written straight onto a
    // <Bar> never passes through it. That half CANNOT be checked here: Recharts
    // draws no series marks under jsdom (the plot area measures zero), so a
    // planted `fill="#3b82f6"` reaches no DOM node to be found. Two versions of
    // a DOM assertion for it passed against their own defect before this was
    // understood. The check that does fail lives in `pack-bans.test.ts`, over
    // the source of the viz layer.
  });

  it("draws every category on the axis", () => {
    render(<ChartRenderer config={{ type: "bar", data: { labels, datasets } }} />);
    for (const label of labels) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });

  it("shows a legend for several series and none for one", () => {
    const { rerender } = render(
      <ChartRenderer config={{ type: "line", data: { labels, datasets } }} />,
    );
    expect(screen.queryByText("Sales")).not.toBeInTheDocument();

    rerender(
      <ChartRenderer
        config={{
          type: "line",
          data: { labels, datasets: [...datasets, { label: "Refunds", data: [1, 2, 3] }] },
        }}
      />,
    );
    expect(screen.getByText("Sales")).toBeInTheDocument();
    expect(screen.getByText("Refunds")).toBeInTheDocument();
  });

  it("frames the chart as the pack's hairline card — no shadow", () => {
    const { container } = render(
      <ChartRenderer config={{ type: "bar", data: { labels, datasets } }} />,
    );
    const frame = container.firstElementChild as HTMLElement;
    expect(frame.className).toContain("border-border");
    expect(frame.className).toContain("rounded-card");
    expect(frame.className).not.toMatch(/\bshadow-/);
  });
});
