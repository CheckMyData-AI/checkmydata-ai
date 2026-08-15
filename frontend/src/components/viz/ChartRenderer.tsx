"use client";

import { Component, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  Scatter,
  ScatterChart,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/shadcn/chart";
import { hasPlottableData, toChartModel } from "./chart-series";

/**
 * Charts run on Recharts through the shadcn chart primitive, so a series colour
 * is `var(--chart-1…5)` from the `ledger` pack rather than a hex in this file.
 * The eight rgba() literals that used to live here were the retired blue/green/
 * amber palette and painted the same chart in both themes.
 */

interface ChartRendererProps {
  config: Record<string, unknown>;
}

class ChartErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <Frame>
          <div className="flex h-full items-center justify-center text-center">
            <div className="space-y-2">
              <p className="text-body text-text-secondary">Chart could not be rendered</p>
              <p className="text-meta text-text-tertiary">
                Try switching to Table view using the toolbar above
              </p>
            </div>
          </div>
        </Frame>
      );
    }
    return this.props.children;
  }
}

/** The pack's card: a hairline at 12% ink, radius 15, and no shadow. */
function Frame({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-[18rem] w-full min-w-0 rounded-card border border-border bg-panel p-4">
      {children}
    </div>
  );
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

const AXIS = {
  stroke: "var(--muted)",
  fontSize: 12,
  tickLine: false,
  axisLine: false,
} as const;

export function ChartRenderer({ config }: ChartRendererProps) {
  const chartType = config.type as string;
  const chartData = config.data as
    | { labels?: unknown[]; datasets?: Array<Record<string, unknown>> }
    | null
    | undefined;

  if (!hasPlottableData(chartData)) {
    return (
      <Frame>
        <div className="flex h-[16rem] items-center justify-center">
          <p className="text-body text-text-secondary">No chart data available</p>
        </div>
      </Frame>
    );
  }

  const { rows, series } = toChartModel(chartData!);
  const chartConfig: ChartConfig = Object.fromEntries(
    series.map((s) => [s.key, { label: s.label, color: s.color }]),
  );

  // The pack caps UI motion at 300ms and stops it entirely under reduced motion.
  // The 800ms staggered draw-on this replaced was over that ceiling by 500ms.
  const animate = !prefersReducedMotion();
  const animation = { isAnimationActive: animate, animationDuration: 300 } as const;

  // One series needs no legend: the axis already says what it is. Several do,
  // and the reference draws exactly this — a coloured dot beside each name.
  const showLegend = series.length > 1 || chartType === "pie";

  return (
    <ChartErrorBoundary>
      <Frame>
        <ChartContainer config={chartConfig} className="max-h-96 min-h-[16rem] w-full">
          {chartType === "bar" ? (
            <BarChart data={rows} accessibilityLayer>
              <CartesianGrid vertical={false} stroke="var(--border)" />
              <XAxis dataKey="label" {...AXIS} interval="preserveStartEnd" />
              <YAxis {...AXIS} width={44} />
              <ChartTooltip content={<ChartTooltipContent />} />
              {showLegend && <ChartLegend content={<ChartLegendContent />} />}
              {series.map((s) => (
                <Bar key={s.key} dataKey={s.key} fill={`var(--color-${s.key})`} radius={2} {...animation} />
              ))}
            </BarChart>
          ) : chartType === "line" ? (
            <LineChart data={rows} accessibilityLayer>
              <CartesianGrid vertical={false} stroke="var(--border)" />
              <XAxis dataKey="label" {...AXIS} interval="preserveStartEnd" />
              <YAxis {...AXIS} width={44} />
              <ChartTooltip content={<ChartTooltipContent />} />
              {showLegend && <ChartLegend content={<ChartLegendContent />} />}
              {series.map((s) => (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  stroke={`var(--color-${s.key})`}
                  strokeWidth={2}
                  dot={false}
                  {...animation}
                />
              ))}
            </LineChart>
          ) : chartType === "pie" ? (
            <PieChart accessibilityLayer>
              <ChartTooltip content={<ChartTooltipContent nameKey="label" hideLabel />} />
              <Pie data={rows} dataKey={series[0].key} nameKey="label" innerRadius={0} {...animation}>
                {rows.map((row, i) => (
                  <Cell key={String(row.label ?? i)} fill={`var(--chart-${(i % 5) + 1})`} />
                ))}
              </Pie>
              <ChartLegend content={<ChartLegendContent nameKey="label" />} />
            </PieChart>
          ) : chartType === "scatter" ? (
            <ScatterChart accessibilityLayer>
              <CartesianGrid stroke="var(--border)" />
              <XAxis dataKey="label" {...AXIS} />
              <YAxis dataKey={series[0].key} {...AXIS} width={44} />
              <ZAxis range={[40, 40]} />
              <ChartTooltip content={<ChartTooltipContent />} />
              {showLegend && <ChartLegend content={<ChartLegendContent />} />}
              {series.map((s) => (
                <Scatter key={s.key} data={rows} dataKey={s.key} fill={`var(--color-${s.key})`} {...animation} />
              ))}
            </ScatterChart>
          ) : (
            <div className="flex h-full items-center justify-center">
              <p className="text-body text-text-secondary">
                Unsupported chart type: &ldquo;{chartType}&rdquo;. Try Table view.
              </p>
            </div>
          )}
        </ChartContainer>
      </Frame>
    </ChartErrorBoundary>
  );
}
