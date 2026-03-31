"use client";

import type { LogSummary } from "@/lib/api";
import { Icon } from "@/components/ui/Icon";

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function fmtMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

function fmtCost(usd: number): string {
  if (usd === 0) return "--";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

interface Props {
  summary: LogSummary;
}

export function LogsSummary({ summary }: Props) {
  const successRate =
    summary.total_requests > 0
      ? ((summary.successful / summary.total_requests) * 100).toFixed(1)
      : "0";

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
      <Card label="Requests" value={fmt(summary.total_requests)} icon="activity" />
      <Card
        label="Success"
        value={`${successRate}%`}
        icon="check"
        valueColor={Number(successRate) > 90 ? "text-success" : "text-warning"}
      />
      <Card
        label="Failed"
        value={fmt(summary.failed)}
        icon="alert-triangle"
        valueColor={summary.failed > 0 ? "text-error" : "text-text-primary"}
      />
      <Card label="LLM Calls" value={fmt(summary.total_llm_calls)} icon="zap" />
      <Card label="DB Queries" value={fmt(summary.total_db_queries)} icon="database" />
      <Card label="Avg Latency" value={fmtMs(summary.avg_duration_ms)} icon="clock" />
      <Card label="Cost" value={fmtCost(summary.total_cost_usd)} icon="layers" />
    </div>
  );
}

function Card({
  label,
  value,
  icon,
  valueColor = "text-text-primary",
}: {
  label: string;
  value: string;
  icon: Parameters<typeof Icon>[0]["name"];
  valueColor?: string;
}) {
  return (
    <div className="bg-surface-1 border border-border-subtle rounded-lg px-3 py-2.5">
      <div className="flex items-center gap-1.5 mb-1">
        <Icon name={icon} size={12} className="text-text-tertiary" />
        <span className="text-[10px] text-text-tertiary uppercase tracking-wider">{label}</span>
      </div>
      <span className={`text-lg font-semibold tabular-nums ${valueColor}`}>{value}</span>
    </div>
  );
}
