"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { CatalogMetricDTO } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { KnowledgeDocs } from "./KnowledgeDocs";
import { InsightFeedPanel } from "@/components/insights/InsightFeedPanel";
import {
  MetricCatalogPanel,
  type CatalogMetric,
} from "@/components/insights/MetricCatalogPanel";

type KnowledgeTab = "docs" | "insights" | "metrics";

function toCatalogMetric(dto: CatalogMetricDTO): CatalogMetric {
  return {
    id: dto.id,
    name: dto.name,
    display_name: dto.display_name,
    description: dto.description,
    category: dto.category,
    source_table: dto.source_table,
    source_column: dto.source_column,
    aggregation: dto.aggregation,
    formula: dto.formula,
    unit: dto.unit,
    data_type: dto.data_type,
    confidence: dto.confidence,
    connection_id: dto.connection_id,
    discovery_source: dto.discovery_source,
    times_referenced: dto.times_referenced,
  };
}

export function KnowledgeHub() {
  const activeProject = useAppStore((s) => s.activeProject);
  const activeConnection = useAppStore((s) => s.activeConnection);
  const [tab, setTab] = useState<KnowledgeTab>("docs");
  const [metrics, setMetrics] = useState<CatalogMetric[]>([]);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [metricsError, setMetricsError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);

  useEffect(() => {
    if (!activeProject || tab !== "metrics") return;
    let cancelled = false;
    setMetricsLoading(true);
    setMetricsError(null);
    api.semanticLayer
      .getCatalog(activeProject.id, activeConnection?.id)
      .then((res) => {
        if (!cancelled) setMetrics(res.metrics.map(toCatalogMetric));
      })
      .catch((e) => {
        if (!cancelled) {
          setMetrics([]);
          setMetricsError(e instanceof Error ? e.message : "Failed to load metrics");
        }
      })
      .finally(() => {
        if (!cancelled) setMetricsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeProject, activeConnection?.id, tab, reloadNonce]);

  if (!activeProject) return null;

  const tabs: { id: KnowledgeTab; label: string }[] = [
    { id: "docs", label: "Docs" },
    { id: "insights", label: "Insights" },
    { id: "metrics", label: "Metrics" },
  ];

  return (
    <div className="flex flex-col min-h-0">
      <div className="flex gap-0.5 px-2 pb-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`flex-1 text-[10px] py-1 rounded transition-colors ${
              tab === t.id
                ? "bg-surface-2 text-text-primary font-medium"
                : "text-text-muted hover:text-text-secondary"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="max-h-64 overflow-y-auto">
        {tab === "docs" && <KnowledgeDocs />}
        {tab === "insights" && (
          <div className="max-h-60 overflow-hidden">
            <InsightFeedPanel />
          </div>
        )}
        {tab === "metrics" && (
          <div className="px-1 pb-2">
            {metricsLoading ? (
              <p className="text-[10px] text-text-tertiary animate-pulse px-2 py-2">
                Loading metrics...
              </p>
            ) : (
              <MetricCatalogPanel
                metrics={metrics}
                error={metricsError}
                onRetry={() => setReloadNonce((n) => n + 1)}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
