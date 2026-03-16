"use client";

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

interface ChartRendererProps {
  config: Record<string, unknown>;
}

export function ChartRenderer({ config }: ChartRendererProps) {
  const chartType = config.type as string;
  const chartData = config.data as {
    labels?: string[];
    datasets?: Array<Record<string, unknown>>;
  };

  if (!chartData?.datasets) return null;

  const coloredDatasets = chartData.datasets.map((ds, i) => {
    const dataLen = Array.isArray(ds.data) ? ds.data.length : 0;
    return {
      ...ds,
      backgroundColor:
        ds.backgroundColor ||
        (chartType === "pie" ? COLORS.slice(0, dataLen) : COLORS[i % COLORS.length]),
      borderColor:
        ds.borderColor ||
        (chartType === "pie" ? COLORS.slice(0, dataLen) : COLORS[i % COLORS.length]),
      borderWidth: ds.borderWidth ?? 1,
    };
  });

  const data = { ...chartData, datasets: coloredDatasets };
  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: "#a1a1aa" } },
    },
    scales:
      chartType !== "pie"
        ? {
            x: { ticks: { color: "#71717a" }, grid: { color: "#27272a" } },
            y: { ticks: { color: "#71717a" }, grid: { color: "#27272a" } },
          }
        : undefined,
    ...(config.options as object || {}),
  };

  return (
    <div className="bg-zinc-900 rounded-lg p-4 h-72">
      {chartType === "bar" && <Bar data={data as never} options={options as never} />}
      {chartType === "line" && <Line data={data as never} options={options as never} />}
      {chartType === "pie" && <Pie data={data as never} options={options as never} />}
      {chartType === "scatter" && <Scatter data={data as never} options={options as never} />}
    </div>
  );
}
