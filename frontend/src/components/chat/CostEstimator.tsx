"use client";

import { useEffect, useState, useRef } from "react";
import { api, type CostEstimate } from "@/lib/api";

interface CostEstimatorProps {
  projectId: string;
  connectionId?: string;
}

export function CostEstimator({ projectId, connectionId }: CostEstimatorProps) {
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  const [showTooltip, setShowTooltip] = useState(false);
  const fetchedKey = useRef("");

  useEffect(() => {
    const key = `${projectId}:${connectionId ?? ""}`;
    if (key === fetchedKey.current) return;
    fetchedKey.current = key;
    let cancelled = false;

    api.chat
      .estimate(projectId, connectionId)
      .then((e) => { if (!cancelled) setEstimate(e); })
      .catch(() => { if (!cancelled) setEstimate(null); });
    return () => { cancelled = true; };
  }, [projectId, connectionId]);

  if (!estimate) return null;

  const { estimated_total_tokens, estimated_cost_usd, context_utilization_pct, breakdown } =
    estimate;

  const barColor =
    context_utilization_pct > 80
      ? "bg-red-500"
      : context_utilization_pct > 60
        ? "bg-amber-500"
        : "bg-emerald-500";

  const formatTokens = (n: number) =>
    n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);

  return (
    <div className="flex items-center gap-2 text-[11px] text-zinc-500">
      <div
        className="relative cursor-default"
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
      >
        <span>~{formatTokens(estimated_total_tokens)} tokens</span>
        {showTooltip && (
          <div className="absolute bottom-full left-0 mb-1.5 z-50 w-52 bg-zinc-800 border border-zinc-700 rounded-lg p-2.5 text-[10px] text-zinc-300 shadow-xl">
            <div className="space-y-1">
              <Row label="Schema" value={breakdown.schema_context} />
              <Row label="Rules" value={breakdown.rules} />
              <Row label="Learnings" value={breakdown.learnings} />
              <Row label="Overview" value={breakdown.overview} />
              <Row label="History budget" value={breakdown.history_budget_remaining} />
              <div className="border-t border-zinc-700 pt-1 mt-1">
                <Row label="Est. prompt" value={estimate.estimated_prompt_tokens} />
                <Row label="Est. completion" value={estimate.estimated_completion_tokens} />
              </div>
            </div>
          </div>
        )}
      </div>

      {estimated_cost_usd != null && estimated_cost_usd > 0 && (
        <span className="px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400">
          ~${estimated_cost_usd < 0.01 ? estimated_cost_usd.toFixed(4) : estimated_cost_usd.toFixed(2)}
        </span>
      )}

      <div className="flex-1 max-w-[80px] h-1 bg-zinc-800 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${barColor}`}
          style={{ width: `${Math.min(100, context_utilization_pct)}%` }}
        />
      </div>
      <span>{context_utilization_pct.toFixed(0)}%</span>
    </div>
  );
}

function Row({ label, value }: { label: string; value: number }) {
  const fmt = value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value);
  return (
    <div className="flex justify-between">
      <span className="text-zinc-500">{label}</span>
      <span>{fmt}</span>
    </div>
  );
}

export { type CostEstimate };
