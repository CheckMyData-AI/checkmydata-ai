"use client";

import { Component, type ReactNode } from "react";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Title,
  Tooltip,
  Legend,
} from "chart.js";
import { Bar, Line, Pie, Scatter } from "react-chartjs-2";

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Title,
  Tooltip,
  Legend,
);

const COLORS = [
  "rgba(59,130,246,0.8)",
  "rgba(16,185,129,0.8)",
  "rgba(245,158,11,0.8)",
  "rgba(239,68,68,0.8)",
  "rgba(139,92,246,0.8)",
  "rgba(236,72,153,0.8)",
  "rgba(14,165,233,0.8)",
  "rgba(168,162,158,0.8)",
];

const BORDER_COLORS = [
  "rgba(59,130,246,1)",
  "rgba(16,185,129,1)",
  "rgba(245,158,11,1)",
  "rgba(239,68,68,1)",
  "rgba(139,92,246,1)",
  "rgba(236,72,153,1)",
  "rgba(14,165,233,1)",
  "rgba(168,162,158,1)",
];

function truncateLabel(label: string, max: number = 20): string {
  return label.length > max ? label.slice(0, max - 1) + "\u2026" : label;
}

interface ChartRendererProps {
  config: Record<string, unknown>;
}

interface ChartErrorBoundaryState {
  hasError: boolean;
}

class ChartErrorBoundary extends Component<
  { children: ReactNode; chartType?: string },
  ChartErrorBoundaryState
> {
  state: ChartErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ChartErrorBoundaryState {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="bg-surface-1 rounded-lg p-4 min-h-[12rem] flex items-center justify-center">
          <div className="text-center space-y-2">
            <p className="text-sm text-text-secondary">
              Chart could not be rendered
            </p>
            <p className="text-xs text-text-tertiary">
              Try switching to Table view using the toolbar above
            </p>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

function validateChartData(
  chartData: { labels?: unknown[]; datasets?: Array<Record<string, unknown>> } | null | undefined,
): boolean {
  if (!chartData?.datasets || !Array.isArray(chartData.datasets)) return false;
  if (chartData.datasets.length === 0) return false;
  return chartData.datasets.some(
    (ds) => Array.isArray(ds.data) && ds.data.length > 0,
  );
}

export function ChartRenderer({ config }: ChartRendererProps) {
  const chartType = config.type as string;
  const chartData = config.data as {
    labels?: string[];
    datasets?: Array<Record<string, unknown>>;
  };

  if (!validateChartData(chartData)) {
    return (
      <div className="bg-surface-1 rounded-lg p-4 min-h-[12rem] flex items-center justify-center">
        <p className="text-sm text-text-secondary">No chart data available</p>
      </div>
    );
  }

  const isSingleSeries = chartData.datasets!.length === 1;

  const coloredDatasets = chartData.datasets!.map((ds, i) => {
    const dataLen = Array.isArray(ds.data) ? ds.data.length : 0;
    const isPie = chartType === "pie";
    return {
      ...ds,
      backgroundColor:
        ds.backgroundColor ||
        (isPie ? COLORS.slice(0, dataLen) : COLORS[i % COLORS.length]),
      borderColor:
        ds.borderColor ||
        (isPie
          ? BORDER_COLORS.slice(0, dataLen)
          : BORDER_COLORS[i % BORDER_COLORS.length]),
      borderWidth: ds.borderWidth ?? (isPie ? 2 : 1),
    };
  });

  const truncatedLabels = chartData.labels?.map((l) =>
    truncateLabel(String(l)),
  );
  const data = { ...chartData, labels: truncatedLabels, datasets: coloredDatasets };

  const options: Record<string, unknown> = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: !isSingleSeries || chartType === "pie",
        labels: { color: "#a1a1aa", boxWidth: 12, padding: 10, font: { size: 11 } },
      },
      tooltip: {
        callbacks:
          chartType === "pie"
            ? {
                label: (ctx: { label?: string; parsed?: number; dataset?: { data?: number[] } }) => {
                  const val = ctx.parsed ?? 0;
                  const total = (ctx.dataset?.data ?? []).reduce((s: number, v: number) => s + v, 0);
                  const pct = total > 0 ? ((val / total) * 100).toFixed(1) : "0";
                  return `${ctx.label}: ${val} (${pct}%)`;
                },
              }
            : undefined,
      },
    },
    scales:
      chartType !== "pie"
        ? {
            x: {
              ticks: {
                color: "#71717a",
                maxRotation: 45,
                autoSkip: true,
                maxTicksLimit: 30,
              },
              grid: { color: "#27272a" },
            },
            y: {
              ticks: { color: "#71717a" },
              grid: { color: "#27272a" },
              beginAtZero: chartType === "bar",
            },
          }
        : undefined,
    ...(typeof config.options === "object" && config.options !== null
      ? config.options
      : {}),
  };

  return (
    <ChartErrorBoundary chartType={chartType}>
      <div className="bg-surface-1 rounded-lg p-4 min-h-[18rem] max-h-96 min-w-0 w-full">
        {chartType === "bar" && (
          <Bar data={data as never} options={options as never} />
        )}
        {chartType === "line" && (
          <Line data={data as never} options={options as never} />
        )}
        {chartType === "pie" && (
          <Pie data={data as never} options={options as never} />
        )}
        {chartType === "scatter" && (
          <Scatter data={data as never} options={options as never} />
        )}
        {!["bar", "line", "pie", "scatter"].includes(chartType) && (
          <div className="flex items-center justify-center h-full">
            <p className="text-sm text-text-secondary">
              Unsupported chart type: &ldquo;{chartType}&rdquo;. Try Table view.
            </p>
          </div>
        )}
      </div>
    </ChartErrorBoundary>
  );
}
