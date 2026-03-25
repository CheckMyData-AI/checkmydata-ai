"use client";

import React, { useState } from "react";

export interface TrendData {
  direction: string;
  slope: number;
  slope_pct_per_period: number;
  strength: number;
  description: string;
  start_value: number;
  end_value: number;
  periods: number;
}

export interface SeasonalityData {
  detected: boolean;
  period: number;
  amplitude: number;
  description: string;
  peak_positions: number[];
  trough_positions: number[];
}

export interface TemporalAnomalyData {
  position: number;
  value: number;
  z_score: number;
  direction: string;
  description: string;
}

export interface TemporalReportData {
  metric_name: string;
  total_points: number;
  trend: TrendData | null;
  seasonality: SeasonalityData | null;
  recent_anomalies: TemporalAnomalyData[];
  context_note: string;
}

interface TemporalReportProps {
  report: TemporalReportData;
}

const TREND_CONFIG: Record<string, { icon: string; color: string }> = {
  up: { icon: "📈", color: "text-success" },
  down: { icon: "📉", color: "text-error" },
  flat: { icon: "➡️", color: "text-text-secondary" },
  volatile: { icon: "〰️", color: "text-warning" },
};

export function TemporalReport({ report }: TemporalReportProps) {
  const [expanded, setExpanded] = useState(false);
  const trendCfg = report.trend
    ? TREND_CONFIG[report.trend.direction] || TREND_CONFIG.flat
    : TREND_CONFIG.flat;

  return (
    <div className="mt-2 rounded-xl border border-border-default bg-accent-muted overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] w-full text-left"
      >
        <span>⏱️</span>
        <span className="font-medium text-accent">
          Temporal Analysis: {report.metric_name}
        </span>
        {report.trend && (
          <span className={`ml-1 ${trendCfg.color}`}>
            {trendCfg.icon}{" "}
            {report.trend.slope_pct_per_period > 0 ? "+" : ""}
            {report.trend.slope_pct_per_period.toFixed(2)}%
          </span>
        )}
        {report.seasonality?.detected && (
          <span className="text-[10px] px-1 py-0.5 rounded bg-accent-muted text-accent">
            seasonal
          </span>
        )}
        {report.recent_anomalies.length > 0 && (
          <span className="text-[10px] px-1 py-0.5 rounded bg-warning-muted text-warning">
            {report.recent_anomalies.length} anomalies
          </span>
        )}
        <span className="ml-auto text-text-muted text-[10px]">
          {report.total_points} points
        </span>
        <svg
          className={`w-3 h-3 text-text-tertiary transition-transform shrink-0 ${expanded ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {expanded && (
        <div className="px-2.5 pb-2 space-y-1.5 border-t border-border-subtle">
          {report.context_note && (
            <div className="text-[11px] text-text-secondary leading-relaxed pt-1.5">
              {report.context_note}
            </div>
          )}

          {report.trend && (
            <div className="text-[11px] space-y-0.5">
              <div className={`font-medium ${trendCfg.color}`}>
                {trendCfg.icon} Trend: {report.trend.description}
              </div>
              <div className="text-text-tertiary text-[10px]">
                From {report.trend.start_value.toFixed(1)} to{" "}
                {report.trend.end_value.toFixed(1)} over{" "}
                {report.trend.periods} periods (fit: {(report.trend.strength * 100).toFixed(0)}%)
              </div>
            </div>
          )}

          {report.seasonality && report.seasonality.detected && (
            <div className="text-[11px] space-y-0.5">
              <div className="font-medium text-accent">
                🔄 Seasonality: {report.seasonality.description}
              </div>
              <div className="text-text-tertiary text-[10px]">
                Amplitude: {report.seasonality.amplitude.toFixed(2)}
              </div>
            </div>
          )}

          {report.recent_anomalies.length > 0 && (
            <div className="text-[11px] space-y-0.5">
              <div className="font-medium text-warning">
                ⚡ Temporal Anomalies
              </div>
              {report.recent_anomalies.map((a, i) => (
                <div key={i} className="text-[10px] text-text-tertiary">
                  Position {a.position}: {a.direction} ({a.z_score}σ) — value{" "}
                  {a.value.toFixed(2)}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
