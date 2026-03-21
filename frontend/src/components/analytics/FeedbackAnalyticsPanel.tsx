"use client";

import { useEffect, useState } from "react";
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

const CATEGORY_LABELS: Record<string, string> = {
  table_preference: "Table Preferences",
  column_usage: "Column Usage",
  data_format: "Data Formats",
  query_pattern: "Query Patterns",
  schema_gotcha: "Schema Gotchas",
  performance_hint: "Performance Hints",
};

interface FeedbackAnalyticsPanelProps {
  projectId: string;
}

export function FeedbackAnalyticsPanel({ projectId }: FeedbackAnalyticsPanelProps) {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    api.dataValidation
      .getFeedbackAnalytics(projectId)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [projectId]);

  if (loading) {
    return (
      <div className="p-6 text-center text-zinc-400">
        Loading analytics...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 text-center text-red-400">
        Failed to load analytics: {error}
      </div>
    );
  }

  if (!data) return null;

  const { validations, learnings, benchmarks, investigations } = data;

  return (
    <div className="space-y-6 p-4">
      <h2 className="text-lg font-semibold text-zinc-100">
        Data Quality Analytics
      </h2>

      {/* Accuracy overview */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard
          label="Total Validations"
          value={validations.total}
        />
        <StatCard
          label="Accuracy Rate"
          value={
            validations.accuracy_rate != null
              ? `${validations.accuracy_rate}%`
              : "N/A"
          }
          highlight={
            validations.accuracy_rate != null && validations.accuracy_rate >= 80
          }
        />
        <StatCard
          label="Active Learnings"
          value={learnings.total_active}
        />
        <StatCard
          label="Benchmarks"
          value={benchmarks.total}
        />
      </div>

      {/* Verdict breakdown */}
      {validations.total > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-medium text-zinc-300">
            Validation Verdicts
          </h3>
          <div className="flex flex-wrap gap-2">
            {Object.entries(validations.by_verdict).map(([verdict, count]) => (
              <span
                key={verdict}
                className={`rounded-full px-3 py-1 text-xs font-medium ${
                  verdict === "confirmed"
                    ? "bg-emerald-900/30 text-emerald-400"
                    : verdict === "rejected"
                      ? "bg-red-900/30 text-red-400"
                      : "bg-zinc-800 text-zinc-400"
                }`}
              >
                {verdict}: {count}
              </span>
            ))}
          </div>
        </section>
      )}

      {/* Error patterns */}
      {validations.top_error_patterns.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-medium text-zinc-300">
            Top Error Patterns
          </h3>
          <ul className="space-y-1">
            {validations.top_error_patterns.map((pattern, i) => (
              <li
                key={i}
                className="flex items-center justify-between rounded bg-zinc-800/50 px-3 py-1.5 text-sm"
              >
                <span className="text-zinc-300">{pattern.reason}</span>
                <span className="text-zinc-500">{pattern.count}x</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Learning breakdown */}
      {learnings.total_active > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-medium text-zinc-300">
            Learnings by Category
          </h3>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {Object.entries(learnings.by_category).map(([cat, count]) => (
              <div
                key={cat}
                className="rounded bg-zinc-800/50 px-3 py-2 text-sm"
              >
                <span className="text-zinc-400">
                  {CATEGORY_LABELS[cat] || cat}
                </span>
                <span className="ml-2 font-medium text-zinc-200">
                  {count}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Investigations */}
      {Object.keys(investigations).length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-medium text-zinc-300">
            Investigations
          </h3>
          <div className="flex flex-wrap gap-2">
            {Object.entries(investigations).map(([status, count]) => (
              <span
                key={status}
                className={`rounded-full px-3 py-1 text-xs font-medium ${
                  status === "resolved"
                    ? "bg-emerald-900/30 text-emerald-400"
                    : status === "failed"
                      ? "bg-red-900/30 text-red-400"
                      : "bg-amber-900/30 text-amber-400"
                }`}
              >
                {status}: {count}
              </span>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string | number;
  highlight?: boolean;
}) {
  return (
    <div className="rounded-lg border border-zinc-700/50 bg-zinc-800/30 px-4 py-3">
      <p className="text-xs text-zinc-500">{label}</p>
      <p
        className={`mt-1 text-xl font-semibold ${
          highlight ? "text-emerald-400" : "text-zinc-100"
        }`}
      >
        {value}
      </p>
    </div>
  );
}
