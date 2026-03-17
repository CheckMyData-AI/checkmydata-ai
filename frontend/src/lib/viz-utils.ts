import { api } from "@/lib/api";
import type { RawResult } from "@/stores/app-store";

export const VIZ_TYPES = [
  { key: "table", label: "Table", icon: "table" },
  { key: "bar_chart", label: "Bar", icon: "bar" },
  { key: "line_chart", label: "Line", icon: "line" },
  { key: "pie_chart", label: "Pie", icon: "pie" },
  { key: "scatter", label: "Scatter", icon: "scatter" },
] as const;

export type VizTypeKey = (typeof VIZ_TYPES)[number]["key"];

export async function rerenderViz(
  rawResult: RawResult,
  vizType: string,
  config?: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return api.viz.render(rawResult.columns, rawResult.rows, vizType, config);
}
