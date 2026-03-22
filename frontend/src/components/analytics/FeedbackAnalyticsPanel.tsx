"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

interface AnalyticsData {
  connections: number;
  validations: {
    total: number;
    by_verdict: Record<string, number>;
    accuracy_rate: number | null;
    top_error_patterns: Array<{ reason: string; count: number }>;
  };
  learnings: {
    total_active: number;
    by_category: Record<string, number>;
  };
  benchmarks: { total: number };
  investigations: Record<string, number>;
}

const VERDICT_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  confirmed: { label: "Confirmed", color: "bg-emerald-400", bg: "text-emerald-400" },
  approximate: { label: "Approximate", color: "bg-amber-400", bg: "text-amber-400" },
  rejected: { label: "Rejected", color: "bg-red-400", bg: "text-red-400" },
  unknown: { label: "Unknown", color: "bg-zinc-500", bg: "text-zinc-500" },
};

interface FeedbackAnalyticsPanelProps {
  projectId: string;
}

export function FeedbackAnalyticsPanel({ projectId }: FeedbackAnalyticsPanelProps) {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((signal?: { cancelled: boolean }) => {
    setLoading(true);
    setError(null);
    api.dataValidation
      .getFeedbackAnalytics(projectId)
      .then((result) => { if (!signal?.cancelled) setData(result); })
      .catch((err) => { if (!signal?.cancelled) setError(String(err)); })
      .finally(() => { if (!signal?.cancelled) setLoading(false); });
  }, [projectId]);

  useEffect(() => {
    const signal = { cancelled: false };
    load(signal);
    return () => { signal.cancelled = true; };
  }, [load]);

  if (loading) {
    return (
      <div className="px-2 py-1 text-[10px] text-zinc-500 animate-pulse">
        Loading analytics...
      </div>
    );
  }

  if (error) {
    return (
      <div className="px-2 py-1 text-[10px] text-red-400 flex items-center gap-2">
        <span>Failed to load analytics</span>
        <button onClick={() => load()} className="text-zinc-400 hover:text-zinc-200 underline">Retry</button>
      </div>
    );
  }

  if (!data || data.validations.total === 0) {
    return (
      <div className="px-2 py-2">
        <p className="text-[11px] text-zinc-500 leading-relaxed">
          No validation data yet. Rate query results with thumbs up/down to start tracking data quality.
        </p>
      </div>
    );
  }

  const { validations, learnings } = data;
  const accuracy = validations.accuracy_rate;
  const confirmed = validations.by_verdict.confirmed ?? 0;
  const total = validations.total;

  return (
    <div className="px-2 py-2 space-y-3">
      <ConfidenceScore accuracy={accuracy} />

      <div className="grid grid-cols-2 gap-2">
        <MiniStat
          label="First-try success"
          value={total > 0 ? `${Math.round((confirmed / total) * 100)}%` : "N/A"}
        />
        <MiniStat
          label="Total learnings"
          value={learnings.total_active}
        />
        <MiniStat
          label="Validations"
          value={total}
        />
        <MiniStat
          label="Benchmarks"
          value={data.benchmarks.total}
        />
      </div>

      <VerdictBar verdicts={validations.by_verdict} total={total} />

      {validations.top_error_patterns.length > 0 && (
        <div className="space-y-1">
          <div className="text-[10px] text-zinc-500">Top errors</div>
          {validations.top_error_patterns.slice(0, 3).map((p, i) => (
            <div key={i} className="flex items-center justify-between text-[10px]">
              <span className="text-zinc-400 truncate mr-2">{p.reason}</span>
              <span className="text-zinc-600 tabular-nums shrink-0">{p.count}x</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ConfidenceScore({ accuracy }: { accuracy: number | null }) {
  if (accuracy == null) {
    return (
      <div className="bg-zinc-800/50 rounded-md px-2.5 py-2">
        <div className="text-[10px] text-zinc-500">Data Confidence</div>
        <div className="text-[12px] font-medium text-zinc-400 mt-0.5">No data yet</div>
      </div>
    );
  }

  const color =
    accuracy >= 80 ? "emerald" :
    accuracy >= 50 ? "amber" :
    "red";

  const barColor = {
    emerald: "bg-emerald-400",
    amber: "bg-amber-400",
    red: "bg-red-400",
  }[color];

  const textColor = {
    emerald: "text-emerald-400",
    amber: "text-amber-400",
    red: "text-red-400",
  }[color];

  return (
    <div className="bg-zinc-800/50 rounded-md px-2.5 py-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-zinc-500">Data Confidence</span>
        <span className={`text-[12px] font-semibold tabular-nums ${textColor}`}>
          {accuracy}%
        </span>
      </div>
      <div className="mt-1.5 h-1.5 bg-zinc-700 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${Math.min(accuracy, 100)}%` }}
        />
      </div>
    </div>
  );
}

function VerdictBar({ verdicts, total }: { verdicts: Record<string, number>; total: number }) {
  if (total === 0) return null;

  const entries = Object.entries(verdicts)
    .filter(([, count]) => count > 0)
    .sort(([a], [b]) => {
      const order = ["confirmed", "approximate", "rejected", "unknown"];
      return order.indexOf(a) - order.indexOf(b);
    });

  return (
    <div className="space-y-1.5">
      <div className="text-[10px] text-zinc-500">Verdict breakdown</div>
      <div className="flex h-2 rounded-full overflow-hidden gap-[1px]">
        {entries.map(([verdict, count]) => {
          const cfg = VERDICT_CONFIG[verdict];
          const pct = (count / total) * 100;
          return (
            <div
              key={verdict}
              className={`${cfg?.color ?? "bg-zinc-600"} transition-all duration-300`}
              style={{ width: `${pct}%` }}
              title={`${cfg?.label ?? verdict}: ${count} (${Math.round(pct)}%)`}
            />
          );
        })}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5">
        {entries.map(([verdict, count]) => {
          const cfg = VERDICT_CONFIG[verdict];
          return (
            <div key={verdict} className="flex items-center gap-1">
              <span className={`w-1.5 h-1.5 rounded-full ${cfg?.color ?? "bg-zinc-600"}`} />
              <span className="text-[9px] text-zinc-500">
                {cfg?.label ?? verdict} {count}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-zinc-800/50 rounded-md px-2 py-1.5">
      <div className="text-[10px] text-zinc-500">{label}</div>
      <div className="text-[12px] font-medium text-zinc-200 tabular-nums mt-0.5">
        {value}
      </div>
    </div>
  );
}
