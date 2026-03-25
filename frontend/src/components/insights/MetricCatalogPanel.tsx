"use client";

import React, { useState, useMemo } from "react";

export interface CatalogMetric {
  id: string;
  name: string;
  display_name: string;
  description: string;
  category: string;
  source_table: string | null;
  source_column: string | null;
  aggregation: string;
  formula: string;
  unit: string;
  data_type: string;
  confidence: number;
  connection_id: string | null;
  discovery_source: string;
  times_referenced: number;
}

interface MetricCatalogPanelProps {
  metrics: CatalogMetric[];
  onMetricClick?: (metric: CatalogMetric) => void;
}

const CATEGORY_CONFIG: Record<string, { icon: string; color: string }> = {
  revenue: { icon: "💰", color: "text-success" },
  cost: { icon: "💸", color: "text-error" },
  conversion: { icon: "🔄", color: "text-accent" },
  engagement: { icon: "👥", color: "text-accent" },
  retention: { icon: "🔁", color: "text-warning" },
  acquisition: { icon: "📈", color: "text-info" },
  performance: { icon: "⚡", color: "text-warning" },
  general: { icon: "📊", color: "text-text-secondary" },
};

export function MetricCatalogPanel({
  metrics,
  onMetricClick,
}: MetricCatalogPanelProps) {
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);

  const categories = useMemo(() => {
    const cats = new Set(metrics.map((m) => m.category));
    return Array.from(cats).sort();
  }, [metrics]);

  const filtered = useMemo(() => {
    let result = metrics;
    if (categoryFilter) {
      result = result.filter((m) => m.category === categoryFilter);
    }
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(
        (m) =>
          m.name.toLowerCase().includes(q) ||
          m.display_name.toLowerCase().includes(q) ||
          m.description.toLowerCase().includes(q),
      );
    }
    return result.sort((a, b) => b.confidence - a.confidence);
  }, [metrics, categoryFilter, search]);

  return (
    <div className="flex flex-col gap-2 h-full">
      <div className="flex items-center gap-2 text-sm font-medium text-text-primary">
        <span>📚</span> Metric Catalog ({metrics.length})
      </div>

      {/* Search */}
      <input
        type="text"
        placeholder="Search metrics..."
        aria-label="Search metrics"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full px-2 py-1 text-[11px] bg-surface-1 border border-border-subtle rounded-lg text-text-primary placeholder-text-muted focus:outline-none focus:border-accent"
      />

      {/* Category filters */}
      <div className="flex flex-wrap gap-1">
        <button
          onClick={() => setCategoryFilter(null)}
          className={`text-[10px] px-1.5 py-0.5 rounded transition-all ${
            !categoryFilter
              ? "bg-surface-3 text-text-primary"
              : "bg-surface-1 text-text-tertiary hover:text-text-primary"
          }`}
        >
          All
        </button>
        {categories.map((cat) => {
          const cfg = CATEGORY_CONFIG[cat] || CATEGORY_CONFIG.general;
          return (
            <button
              key={cat}
              onClick={() =>
                setCategoryFilter(categoryFilter === cat ? null : cat)
              }
              className={`text-[10px] px-1.5 py-0.5 rounded transition-all ${
                categoryFilter === cat
                  ? "bg-surface-3 text-text-primary"
                  : "bg-surface-1 text-text-tertiary hover:text-text-primary"
              }`}
            >
              {cfg.icon} {cat}
            </button>
          );
        })}
      </div>

      {/* Metric list */}
      <div className="flex-1 overflow-y-auto space-y-1">
        {filtered.length === 0 && (
          <div className="text-[11px] text-text-muted py-4 text-center">
            No metrics found
          </div>
        )}
        {filtered.map((m) => {
          const cfg =
            CATEGORY_CONFIG[m.category] || CATEGORY_CONFIG.general;
          return (
            <button
              key={m.id}
              onClick={() => onMetricClick?.(m)}
              className="w-full text-left px-2 py-1.5 rounded border border-border-subtle/50 bg-surface-1/50 hover:bg-surface-2/50 transition-all group"
            >
              <div className="flex items-center gap-1.5">
                <span className="text-[10px]">{cfg.icon}</span>
                <span
                  className={`text-[11px] font-medium ${cfg.color} truncate`}
                  title={m.display_name}
                >
                  {m.display_name}
                </span>
                {m.aggregation && (
                  <span className="text-[10px] px-1 py-0.5 rounded bg-surface-2 text-text-tertiary shrink-0">
                    {m.aggregation}
                  </span>
                )}
                {m.unit && (
                  <span className="text-[10px] text-text-muted shrink-0">
                    {m.unit}
                  </span>
                )}
                <span className="ml-auto text-[10px] text-text-muted shrink-0">
                  {Math.round(m.confidence * 100)}%
                </span>
              </div>
              {m.description && (
                <div className="text-[10px] text-text-muted mt-0.5 truncate">
                  {m.description}
                </div>
              )}
              <div className="text-[10px] text-text-muted mt-0.5">
                {m.source_table && (
                  <span>
                    {m.source_table}
                    {m.source_column ? `.${m.source_column}` : ""}
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
