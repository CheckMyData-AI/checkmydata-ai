"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import type { UsageStatsResponse } from "@/lib/api";

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function formatCost(usd: number | null): string {
  if (usd == null || usd === 0) return "--";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

function ChangeBadge({ value }: { value: number | null }) {
  if (value == null || value === 0) return <span className="text-[10px] text-zinc-500">--</span>;
  const isUp = value > 0;
  return (
    <span
      className={`text-[10px] font-medium ${isUp ? "text-amber-400" : "text-emerald-400"}`}
    >
      {isUp ? "+" : ""}{value.toFixed(1)}%
    </span>
  );
}

function MiniBarChart({ data }: { data: { date: string; total_tokens: number }[] }) {
  if (!data.length) return null;
  const max = Math.max(...data.map((d) => d.total_tokens), 1);

  return (
    <div className="flex items-end gap-[2px] h-10 mt-2">
      {data.map((d) => {
        const pct = (d.total_tokens / max) * 100;
        return (
          <div
            key={d.date}
            className="flex-1 min-w-[3px] rounded-t bg-violet-500/60 hover:bg-violet-400/80 transition-colors cursor-default"
            style={{ height: `${Math.max(pct, 2)}%` }}
            title={`${d.date}: ${d.total_tokens.toLocaleString()} tokens`}
          />
        );
      })}
    </div>
  );
}

interface UsageStatsPanelProps {
  compact?: boolean;
}

export function UsageStatsPanel({ compact = false }: UsageStatsPanelProps) {
  const [stats, setStats] = useState<UsageStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.usage.getStats(30);
      setStats(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load usage stats");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <div className="px-2 py-1 text-[10px] text-zinc-500 animate-pulse">
        Loading usage...
      </div>
    );
  }

  if (error) {
    return (
      <div className="px-2 py-1 text-[10px] text-red-400 flex items-center gap-2">
        <span>{error}</span>
        <button onClick={load} className="text-zinc-400 hover:text-zinc-200 underline">Retry</button>
      </div>
    );
  }

  if (!stats) return null;

  const { current_period: cur, change_percent: change } = stats;

  if (compact) {
    return (
      <div className="px-2 py-1 space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-zinc-500">30-day tokens</span>
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] font-medium text-zinc-300 tabular-nums">
              {formatNumber(cur.total_tokens)}
            </span>
            <ChangeBadge value={change.total_tokens} />
          </div>
        </div>
        {cur.estimated_cost_usd != null && cur.estimated_cost_usd > 0 && (
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-zinc-500">Est. cost</span>
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] font-medium text-zinc-300 tabular-nums">
                {formatCost(cur.estimated_cost_usd)}
              </span>
              <ChangeBadge value={change.estimated_cost_usd} />
            </div>
          </div>
        )}
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-zinc-500">Requests</span>
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] font-medium text-zinc-300 tabular-nums">
              {cur.request_count.toLocaleString()}
            </span>
            <ChangeBadge value={change.request_count} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="px-2 py-2 space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <StatCard
          label="Input tokens"
          value={formatNumber(cur.prompt_tokens)}
          change={change.prompt_tokens}
        />
        <StatCard
          label="Output tokens"
          value={formatNumber(cur.completion_tokens)}
          change={change.completion_tokens}
        />
        <StatCard
          label="Total tokens"
          value={formatNumber(cur.total_tokens)}
          change={change.total_tokens}
        />
        <StatCard
          label="Est. cost"
          value={formatCost(cur.estimated_cost_usd)}
          change={change.estimated_cost_usd}
        />
      </div>

      <div className="flex items-center justify-between text-[10px] text-zinc-500">
        <span>Requests: {cur.request_count.toLocaleString()}</span>
        <span>vs prev {stats.period_days}d</span>
      </div>

      {stats.daily_breakdown.length > 0 && (
        <div>
          <div className="text-[10px] text-zinc-500 mb-1">Daily tokens ({stats.period_days}d)</div>
          <MiniBarChart data={stats.daily_breakdown} />
          <div className="flex justify-between text-[9px] text-zinc-600 mt-0.5">
            <span>{stats.daily_breakdown[0]?.date}</span>
            <span>{stats.daily_breakdown[stats.daily_breakdown.length - 1]?.date}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  change,
}: {
  label: string;
  value: string;
  change: number | null;
}) {
  return (
    <div className="bg-zinc-800/50 rounded-md px-2 py-1.5">
      <div className="text-[10px] text-zinc-500">{label}</div>
      <div className="flex items-center gap-1.5 mt-0.5">
        <span className="text-[12px] font-medium text-zinc-200 tabular-nums">{value}</span>
        <ChangeBadge value={change} />
      </div>
    </div>
  );
}
