import { describe, expect, it } from "vitest";
import {
  hasPlottableData,
  seriesColor,
  toChartModel,
  truncateLabel,
} from "@/components/viz/chart-series";

describe("hasPlottableData", () => {
  it("refuses a config with nothing in it", () => {
    expect(hasPlottableData(null)).toBe(false);
    expect(hasPlottableData(undefined)).toBe(false);
    expect(hasPlottableData({ datasets: [] })).toBe(false);
    expect(hasPlottableData({ labels: ["a"], datasets: [{ label: "X", data: [] }] })).toBe(false);
  });

  it("accepts a config where at least one series carries data", () => {
    expect(
      hasPlottableData({ labels: ["a"], datasets: [{ label: "X", data: [] }, { label: "Y", data: [1] }] }),
    ).toBe(true);
  });
});

describe("seriesColor — the pack ships five hues and the sixth is derived", () => {
  it("uses the pack's ramp for the first five, in order", () => {
    expect([0, 1, 2, 3, 4].map(seriesColor)).toEqual([
      "var(--chart-1)",
      "var(--chart-2)",
      "var(--chart-3)",
      "var(--chart-4)",
      "var(--chart-5)",
    ]);
  });

  it("never repeats a colour exactly on the next lap", () => {
    // Two identical hues in one chart is the failure this rule exists to
    // prevent; a plain modulo would give series 6 the same value as series 1.
    expect(seriesColor(5)).not.toBe(seriesColor(0));
    expect(seriesColor(5)).toContain("var(--chart-1)");
    expect(seriesColor(5)).toContain("color-mix");
  });

  it("keeps twelve series distinct from one another", () => {
    const colors = Array.from({ length: 12 }, (_, i) => seriesColor(i));
    expect(new Set(colors).size).toBe(12);
  });

  it("never emits a raw colour literal — every series resolves through a token", () => {
    for (let i = 0; i < 12; i++) {
      expect(seriesColor(i)).not.toMatch(/#[0-9a-f]{3,8}|rgba?\(|hsla?\(/i);
    }
  });
});

describe("toChartModel — the transpose Recharts needs", () => {
  const data = {
    labels: ["Jan", "Feb", "Mar"],
    datasets: [
      { label: "Organic", data: [10, 20, 30] },
      { label: "Paid", data: [1, 2, 3] },
    ],
  };

  it("turns one array per series into one object per category", () => {
    const { rows } = toChartModel(data);
    expect(rows).toEqual([
      { label: "Jan", s0: 10, s1: 1 },
      { label: "Feb", s0: 20, s1: 2 },
      { label: "Mar", s0: 30, s1: 3 },
    ]);
  });

  it("names each series and gives it a token colour", () => {
    const { series } = toChartModel(data);
    expect(series).toEqual([
      { key: "s0", label: "Organic", color: "var(--chart-1)" },
      { key: "s1", label: "Paid", color: "var(--chart-2)" },
    ]);
  });

  it("sizes the rows by the LONGEST series, not by the labels", () => {
    // A short `labels` array with a longer series silently drops the tail when
    // the row count is driven by the labels — the off-by-one this guards.
    const { rows } = toChartModel({
      labels: ["Jan"],
      datasets: [{ label: "Organic", data: [10, 20, 30] }],
    });
    expect(rows).toHaveLength(3);
    expect(rows[2]).toEqual({ label: "3", s0: 30 });
  });

  it("keeps a hole as null rather than inventing a zero", () => {
    const { rows } = toChartModel({
      labels: ["Jan", "Feb"],
      datasets: [{ label: "Organic", data: [10] }],
    });
    expect(rows[1].s0).toBeNull();
  });

  it("reads numeric strings and scatter points", () => {
    const { rows } = toChartModel({
      labels: ["a", "b"],
      datasets: [{ label: "S", data: ["12.5", { x: 1, y: 7 }] }],
    });
    expect(rows[0].s0).toBe(12.5);
    expect(rows[1].s0).toBe(7);
  });

  it("falls back to a numbered name rather than an empty legend entry", () => {
    const { series } = toChartModel({ labels: ["a"], datasets: [{ data: [1] }] });
    expect(series[0].label).toBe("Series 1");
  });
});

describe("truncateLabel", () => {
  it("leaves a short label alone and ellipsises a long one", () => {
    expect(truncateLabel("Jan")).toBe("Jan");
    expect(truncateLabel("a".repeat(30))).toHaveLength(20);
    expect(truncateLabel("a".repeat(30)).endsWith("…")).toBe(true);
  });
});
