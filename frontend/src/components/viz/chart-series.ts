/**
 * The adapter between the agent's chart config and Recharts.
 *
 * The backend's VizAgent emits a Chart.js-shaped object — `{ type, data: {
 * labels, datasets }, options }` — and that contract is not this redesign's to
 * break, so the shape is translated here rather than at the source. Everything
 * in this file is pure, which is the point: the colour rule and the reshaping
 * are the two places a chart silently goes wrong, and both are testable without
 * rendering anything.
 */

export interface ChartDataset {
  label?: string;
  data?: unknown[];
  [key: string]: unknown;
}

export interface ChartSeries {
  /** The row key Recharts reads — `s0`, `s1`, … Stable across renders. */
  key: string;
  label: string;
  color: string;
}

export interface ChartModel {
  rows: Array<Record<string, string | number | null>>;
  series: ChartSeries[];
}

/** Long category names push the plot area to nothing; the reference truncates. */
export function truncateLabel(label: string, max = 20): string {
  return label.length > max ? label.slice(0, max - 1) + "…" : label;
}

/**
 * The pack ships five chart hues and no more. Past the fifth series the ramp
 * repeats, darkened toward the ink one step per lap — a DERIVED rule, because
 * the reference's dashboard never shows more than five series and so never had
 * to answer this. Stated rather than silently cycled: two identical hues in one
 * chart is the failure, and a reader can see the difference between lap one and
 * lap two even when they cannot name it.
 */
export function seriesColor(index: number): string {
  const slot = (index % 5) + 1;
  const lap = Math.floor(index / 5);
  const base = `var(--chart-${slot})`;
  if (lap === 0) return base;
  const mix = Math.min(20 + lap * 15, 65);
  return `color-mix(in oklab, ${base} ${100 - mix}%, var(--ink))`;
}

/** A dataset carries data; anything else is a legend entry with nothing behind it. */
export function hasPlottableData(
  data: { labels?: unknown[]; datasets?: ChartDataset[] } | null | undefined,
): boolean {
  if (!data?.datasets || !Array.isArray(data.datasets)) return false;
  if (data.datasets.length === 0) return false;
  return data.datasets.some((ds) => Array.isArray(ds.data) && ds.data.length > 0);
}

function toNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  // Scatter datasets carry `{x, y}` points; the y is the value on a category axis.
  if (value && typeof value === "object" && "y" in (value as Record<string, unknown>)) {
    return toNumber((value as Record<string, unknown>).y);
  }
  return null;
}

/**
 * Chart.js keeps one array per series; Recharts wants one object per category.
 * The transpose is where an off-by-one silently drops the last bar, which is why
 * the row count is driven by the longest series rather than by `labels`.
 */
export function toChartModel(data: {
  labels?: unknown[];
  datasets?: ChartDataset[];
}): ChartModel {
  const datasets = data.datasets ?? [];
  const series: ChartSeries[] = datasets.map((ds, i) => ({
    key: `s${i}`,
    label: typeof ds.label === "string" && ds.label ? ds.label : `Series ${i + 1}`,
    color: seriesColor(i),
  }));

  // The MAX of both sides, and it has to be both. Driving the count from
  // `labels` drops the tail of a longer series; driving it from the datasets
  // drops a category the agent labelled but has no number for yet — and the
  // second is the one a test caught, because a missing bar reads as "zero"
  // rather than as "absent".
  const length = datasets.reduce(
    (max, ds) => Math.max(max, Array.isArray(ds.data) ? ds.data.length : 0),
    data.labels?.length ?? 0,
  );

  const rows = Array.from({ length }, (_, r) => {
    const row: Record<string, string | number | null> = {
      label: truncateLabel(String(data.labels?.[r] ?? r + 1)),
    };
    datasets.forEach((ds, i) => {
      row[`s${i}`] = toNumber(Array.isArray(ds.data) ? ds.data[r] : undefined);
    });
    return row;
  });

  return { rows, series };
}
