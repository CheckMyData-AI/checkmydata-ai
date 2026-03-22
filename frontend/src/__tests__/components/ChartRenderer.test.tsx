import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("react-chartjs-2", () => ({
  Bar: (props: any) => <div data-testid="chart-bar" />,
  Line: (props: any) => <div data-testid="chart-line" />,
  Pie: (props: any) => <div data-testid="chart-pie" />,
  Scatter: (props: any) => <div data-testid="chart-scatter" />,
}));

vi.mock("chart.js", () => ({
  Chart: { register: vi.fn() },
  CategoryScale: class {},
  LinearScale: class {},
  PointElement: class {},
  LineElement: class {},
  BarElement: class {},
  ArcElement: class {},
  Title: class {},
  Tooltip: class {},
  Legend: class {},
}));

const { ChartRenderer } = await import("@/components/viz/ChartRenderer");

const validDatasets = [{ label: "Sales", data: [10, 20, 30] }];
const validLabels = ["Jan", "Feb", "Mar"];

describe("ChartRenderer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows "No chart data available" when config.data is null', () => {
    render(<ChartRenderer config={{ type: "bar", data: null }} />);
    expect(screen.getByText("No chart data available")).toBeInTheDocument();
  });

  it('shows "No chart data available" when datasets is empty', () => {
    render(
      <ChartRenderer
        config={{ type: "bar", data: { labels: validLabels, datasets: [] } }}
      />,
    );
    expect(screen.getByText("No chart data available")).toBeInTheDocument();
  });

  it('shows "No chart data available" when datasets[0].data is empty', () => {
    render(
      <ChartRenderer
        config={{
          type: "bar",
          data: { labels: validLabels, datasets: [{ label: "X", data: [] }] },
        }}
      />,
    );
    expect(screen.getByText("No chart data available")).toBeInTheDocument();
  });

  it('shows "No chart data available" when data is undefined', () => {
    render(<ChartRenderer config={{ type: "line" }} />);
    expect(screen.getByText("No chart data available")).toBeInTheDocument();
  });

  it("renders bar chart container", () => {
    render(
      <ChartRenderer
        config={{
          type: "bar",
          data: { labels: validLabels, datasets: validDatasets },
        }}
      />,
    );
    expect(screen.getByTestId("chart-bar")).toBeInTheDocument();
  });

  it("renders line chart container", () => {
    render(
      <ChartRenderer
        config={{
          type: "line",
          data: { labels: validLabels, datasets: validDatasets },
        }}
      />,
    );
    expect(screen.getByTestId("chart-line")).toBeInTheDocument();
  });

  it("renders pie chart container", () => {
    render(
      <ChartRenderer
        config={{
          type: "pie",
          data: { labels: validLabels, datasets: validDatasets },
        }}
      />,
    );
    expect(screen.getByTestId("chart-pie")).toBeInTheDocument();
  });

  it("renders scatter chart container", () => {
    render(
      <ChartRenderer
        config={{
          type: "scatter",
          data: { labels: validLabels, datasets: validDatasets },
        }}
      />,
    );
    expect(screen.getByTestId("chart-scatter")).toBeInTheDocument();
  });

  it("does not render wrong chart type element for bar", () => {
    render(
      <ChartRenderer
        config={{
          type: "bar",
          data: { labels: validLabels, datasets: validDatasets },
        }}
      />,
    );
    expect(screen.queryByTestId("chart-line")).not.toBeInTheDocument();
    expect(screen.queryByTestId("chart-pie")).not.toBeInTheDocument();
    expect(screen.queryByTestId("chart-scatter")).not.toBeInTheDocument();
  });
});
