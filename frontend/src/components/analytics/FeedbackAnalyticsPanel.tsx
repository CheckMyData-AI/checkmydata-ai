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
  confirmed: { label: "Confirmed", color: "bg-success", bg: "text-success" },
  approximate: { label: "Approximate", color: "bg-warning", bg: "text-warning" },
  rejected: { label: "Rejected", color: "bg-error", bg: "text-error" },
  unknown: { label: "Unknown", color: "bg-surface-3", bg: "text-text-tertiary" },
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
      <div className="px-2 py-1 text-[10px] text-text-tertiary animate-pulse">
        Loading analytics...
      </div>
    );
  }

  if (error) {
    return (
      <div className="px-2 py-1 text-[10px] text-error flex items-center gap-2">
        <span>Failed to load analytics</span>
        <button onClick={() => load()} className="text-text-secondary hover:text-text-primary underline">Retry</button>
      </div>
    );
  }

  if (!data || data.validations.total === 0) {
    return (
      <div className="px-2 py-2">
        <p className="text-[11px] text-text-tertiary leading-relaxed">
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
          <div className="text-[10px] text-text-tertiary">Top errors</div>
          {validations.top_error_patterns.slice(0, 3).map((p, i) => (
            <div key={i} className="flex items-center justify-between text-[10px]">
              <span className="text-text-secondary truncate mr-2">{p.reason}</span>
              <span className="text-text-muted tabular-nums shrink-0">{p.count}x</span>
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
      <div className="bg-surface-2/50 rounded-md px-2.5 py-2">
        <div className="text-[10px] text-text-tertiary">Data Confidence</div>
        <div className="text-sm font-medium text-text-secondary mt-0.5">No data yet</div>
      </div>
    );
  }

  const color =
    accuracy >= 80 ? "emerald" :
    accuracy >= 50 ? "amber" :
    "red";

  const barColor = {
    emerald: "bg-success",
    amber: "bg-warning",
    red: "bg-error",
  }[color];

  const textColor = {
    emerald: "text-success",
    amber: "text-warning",
    red: "text-error",
  }[color];

  return (
    <div className="bg-surface-2/50 rounded-md px-2.5 py-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-text-tertiary">Data Confidence</span>
        <span className={`text-sm font-semibold tabular-nums ${textColor}`}>
          {accuracy}%
        </span>
      </div>
      <div className="mt-1.5 h-1.5 bg-surface-3 rounded-full overflow-hidden">
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
      <div className="text-[10px] text-text-tertiary">Verdict breakdown</div>
      <div className="flex h-2 rounded-full overflow-hidden gap-[1px]">
        {entries.map(([verdict, count]) => {
          const cfg = VERDICT_CONFIG[verdict];
          const pct = (count / total) * 100;
          return (
            <div
              key={verdict}
              className={`${cfg?.color ?? "bg-surface-3"} transition-all duration-300`}
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
              <span className={`w-1.5 h-1.5 rounded-full ${cfg?.color ?? "bg-surface-3"}`} />
              <span className="text-[10px] text-text-tertiary">
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
    <div className="bg-surface-2/50 rounded-md px-2 py-1.5">
      <div className="text-[10px] text-text-tertiary">{label}</div>
      <div className="text-sm font-medium text-text-primary tabular-nums mt-0.5">
        {value}
      </div>
    </div>
  );
}
