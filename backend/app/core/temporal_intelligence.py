"""Temporal Intelligence Engine.

Analyzes time series data to detect trends, seasonality, and lagged
effects. Uses pure Python math (no statsmodels/scipy) to keep
dependencies light.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

MIN_POINTS_TREND = 3
MIN_POINTS_SEASONALITY = 14
TREND_SIGNIFICANCE_THRESHOLD = 0.02


@dataclass
class TrendResult:
    """Detected trend in a time series."""

    direction: str  # up, down, flat, volatile
    slope: float
    slope_pct_per_period: float
    strength: float  # 0-1 (R² of linear fit)
    description: str
    start_value: float = 0.0
    end_value: float = 0.0
    periods: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SeasonalityResult:
    """Detected seasonality pattern."""

    detected: bool
    period: int  # number of periods in one cycle (7=weekly, 30=monthly)
    amplitude: float  # strength of seasonal effect
    description: str
    peak_positions: list[int] = field(default_factory=list)
    trough_positions: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LagResult:
    """Detected lag/lead relationship between two series."""

    lag_periods: int  # positive = series_b lags behind series_a
    correlation: float
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TemporalReport:
    """Full temporal analysis report for a time series."""

    metric_name: str
    total_points: int
    trend: TrendResult | None = None
    seasonality: SeasonalityResult | None = None
    recent_anomalies: list[dict[str, Any]] = field(default_factory=list)
    context_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "total_points": self.total_points,
            "trend": self.trend.to_dict() if self.trend else None,
            "seasonality": (self.seasonality.to_dict() if self.seasonality else None),
            "recent_anomalies": self.recent_anomalies,
            "context_note": self.context_note,
        }


class TemporalIntelligenceService:
    """Pure-Python temporal analysis without heavy ML dependencies."""

    def analyze_series(
        self,
        values: list[float],
        metric_name: str = "metric",
        period_label: str = "day",
    ) -> TemporalReport:
        """Run full temporal analysis on a time series."""
        if not values or len(values) < MIN_POINTS_TREND:
            return TemporalReport(
                metric_name=metric_name,
                total_points=len(values),
                context_note=(
                    f"Insufficient data ({len(values)} points) for analysis. "
                    f"Need at least {MIN_POINTS_TREND}."
                ),
            )

        trend = self.detect_trend(values, period_label)
        seasonality = None
        if len(values) >= MIN_POINTS_SEASONALITY:
            seasonality = self.detect_seasonality(values, period_label)

        anomalies = self.detect_temporal_anomalies(values, trend, seasonality)

        context = self._build_context(trend, seasonality, period_label)

        return TemporalReport(
            metric_name=metric_name,
            total_points=len(values),
            trend=trend,
            seasonality=seasonality,
            recent_anomalies=anomalies,
            context_note=context,
        )

    def detect_trend(self, values: list[float], period_label: str = "day") -> TrendResult:
        """Detect linear trend using least-squares regression."""
        n = len(values)
        if n < MIN_POINTS_TREND:
            return TrendResult(
                direction="flat",
                slope=0.0,
                slope_pct_per_period=0.0,
                strength=0.0,
                description="Insufficient data for trend detection",
            )

        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n

        numerator = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return TrendResult(
                direction="flat",
                slope=0.0,
                slope_pct_per_period=0.0,
                strength=0.0,
                description="Constant values — no trend",
            )

        slope = numerator / denominator

        ss_res = sum((values[i] - (y_mean + slope * (i - x_mean))) ** 2 for i in range(n))
        ss_tot = sum((v - y_mean) ** 2 for v in values)
        r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
        r_squared = max(0.0, min(1.0, r_squared))

        base = abs(y_mean) if y_mean != 0 else 1.0
        slope_pct = (slope / base) * 100

        if abs(slope_pct) < TREND_SIGNIFICANCE_THRESHOLD:
            direction = "flat"
        elif r_squared < 0.1:
            direction = "volatile"
        elif slope > 0:
            direction = "up"
        else:
            direction = "down"

        descriptions = {
            "up": (f"Upward trend: +{slope_pct:.2f}% per {period_label} (R²={r_squared:.2f})"),
            "down": (f"Downward trend: {slope_pct:.2f}% per {period_label} (R²={r_squared:.2f})"),
            "flat": f"No significant trend detected (R²={r_squared:.2f})",
            "volatile": (
                f"Volatile — slope exists ({slope_pct:.2f}%/{period_label}) "
                f"but low fit (R²={r_squared:.2f})"
            ),
        }

        return TrendResult(
            direction=direction,
            slope=round(slope, 6),
            slope_pct_per_period=round(slope_pct, 4),
            strength=round(r_squared, 4),
            description=descriptions.get(direction, "Unknown"),
            start_value=values[0],
            end_value=values[-1],
            periods=n,
        )

    def detect_seasonality(
        self, values: list[float], period_label: str = "day"
    ) -> SeasonalityResult:
        """Detect seasonality using autocorrelation analysis."""
        n = len(values)
        if n < MIN_POINTS_SEASONALITY:
            return SeasonalityResult(
                detected=False,
                period=0,
                amplitude=0.0,
                description="Insufficient data for seasonality detection",
            )

        mean = sum(values) / n
        x_mean = (n - 1) / 2.0
        num = sum((i - x_mean) * (values[i] - mean) for i in range(n))
        den = sum((i - x_mean) ** 2 for i in range(n))
        lin_slope = num / den if den > 0 else 0.0
        detrended = [values[i] - (mean + lin_slope * (i - x_mean)) for i in range(n)]
        variance = sum(d * d for d in detrended) / n

        if variance < 1e-10:
            return SeasonalityResult(
                detected=False,
                period=0,
                amplitude=0.0,
                description="Near-zero variance — no seasonality",
            )

        candidate_periods = [7, 14, 28, 30, 12, 4, 52]
        best_period = 0
        best_autocorr = 0.0

        for period in candidate_periods:
            if period >= n // 2:
                continue
            autocorr = self._autocorrelation(detrended, period, variance)
            if autocorr > best_autocorr:
                best_autocorr = autocorr
                best_period = period

        if best_autocorr < 0.3 or best_period == 0:
            return SeasonalityResult(
                detected=False,
                period=0,
                amplitude=0.0,
                description=(
                    f"No significant seasonality detected (best autocorr: {best_autocorr:.2f})"
                ),
            )

        peaks: list[int] = []
        troughs: list[int] = []
        for i in range(best_period, n - best_period):
            window = values[i - 1 : i + 2]
            if len(window) == 3 and window[1] == max(window):
                peaks.append(i)
            elif len(window) == 3 and window[1] == min(window):
                troughs.append(i)

        amplitude = (max(values) - min(values)) / 2 if values else 0.0

        period_name = self._period_name(best_period, period_label)

        return SeasonalityResult(
            detected=True,
            period=best_period,
            amplitude=round(amplitude, 4),
            description=(
                f"Detected {period_name} seasonality "
                f"(period={best_period}, autocorr={best_autocorr:.2f})"
            ),
            peak_positions=peaks[:5],
            trough_positions=troughs[:5],
        )

    def detect_temporal_anomalies(
        self,
        values: list[float],
        trend: TrendResult | None = None,
        seasonality: SeasonalityResult | None = None,
        z_threshold: float = 2.5,
    ) -> list[dict[str, Any]]:
        """Detect anomalous points considering trend and seasonality."""
        if len(values) < MIN_POINTS_TREND:
            return []

        residuals = list(values)
        n = len(values)
        mean = sum(values) / n

        if trend and trend.strength > 0.3:
            x_mean = (n - 1) / 2.0
            residuals = [values[i] - (mean + trend.slope * (i - x_mean)) for i in range(n)]

        r_mean = sum(residuals) / n
        r_std = math.sqrt(sum((r - r_mean) ** 2 for r in residuals) / max(n - 1, 1))

        if r_std < 1e-10:
            return []

        anomalies: list[dict[str, Any]] = []
        for i in range(n):
            z = abs(residuals[i] - r_mean) / r_std
            if z >= z_threshold:
                direction = "spike" if residuals[i] > r_mean else "dip"
                anomalies.append(
                    {
                        "position": i,
                        "value": values[i],
                        "z_score": round(z, 2),
                        "direction": direction,
                        "description": (
                            f"Temporal {direction} at position {i}: "
                            f"value={values[i]:.2f}, z={z:.1f}σ"
                        ),
                    }
                )

        return anomalies

    def detect_lag(
        self,
        series_a: list[float],
        series_b: list[float],
        max_lag: int = 14,
    ) -> LagResult:
        """Find the lag with highest cross-correlation between two series."""
        n = min(len(series_a), len(series_b))
        if n < MIN_POINTS_TREND:
            return LagResult(
                lag_periods=0,
                correlation=0.0,
                description="Insufficient data for lag detection",
            )

        a = series_a[:n]
        b = series_b[:n]
        a_mean = sum(a) / n
        b_mean = sum(b) / n
        a_std = math.sqrt(sum((x - a_mean) ** 2 for x in a) / n)
        b_std = math.sqrt(sum((x - b_mean) ** 2 for x in b) / n)

        if a_std < 1e-10 or b_std < 1e-10:
            return LagResult(
                lag_periods=0,
                correlation=0.0,
                description="One or both series have near-zero variance",
            )

        best_lag = 0
        best_corr = -1.0

        for lag in range(-min(max_lag, n // 3), min(max_lag, n // 3) + 1):
            corr = self._cross_correlation(a, b, lag, a_mean, b_mean, a_std, b_std)
            if corr > best_corr:
                best_corr = corr
                best_lag = lag

        if best_corr < 0.3:
            return LagResult(
                lag_periods=0,
                correlation=round(best_corr, 4),
                description=(f"No significant lag relationship found (best corr={best_corr:.2f})"),
            )

        if best_lag > 0:
            desc = f"Series B lags behind Series A by {best_lag} periods (corr={best_corr:.2f})"
        elif best_lag < 0:
            desc = (
                f"Series A lags behind Series B by {abs(best_lag)} periods (corr={best_corr:.2f})"
            )
        else:
            desc = f"Series are synchronized (corr={best_corr:.2f})"

        return LagResult(
            lag_periods=best_lag,
            correlation=round(best_corr, 4),
            description=desc,
        )

    @staticmethod
    def _autocorrelation(detrended: list[float], lag: int, variance: float) -> float:
        n = len(detrended)
        if lag >= n or variance < 1e-10:
            return 0.0
        cov = sum(detrended[i] * detrended[i + lag] for i in range(n - lag))
        return cov / ((n - lag) * variance)

    @staticmethod
    def _cross_correlation(
        a: list[float],
        b: list[float],
        lag: int,
        a_mean: float,
        b_mean: float,
        a_std: float,
        b_std: float,
    ) -> float:
        n = len(a)
        count = 0
        total = 0.0
        for i in range(n):
            j = i + lag
            if 0 <= j < n:
                total += (a[i] - a_mean) * (b[j] - b_mean)
                count += 1
        if count == 0:
            return 0.0
        return total / (count * a_std * b_std)

    @staticmethod
    def _build_context(
        trend: TrendResult,
        seasonality: SeasonalityResult | None,
        period_label: str,
    ) -> str:
        parts: list[str] = []
        if trend.direction == "up":
            parts.append(
                f"Overall upward trend ({trend.slope_pct_per_period:+.2f}%/{period_label})"
            )
        elif trend.direction == "down":
            parts.append(
                f"Overall downward trend ({trend.slope_pct_per_period:+.2f}%/{period_label})"
            )
        elif trend.direction == "volatile":
            parts.append("Data is volatile — no clear directional trend")
        else:
            parts.append("No significant trend detected")

        if seasonality and seasonality.detected:
            parts.append(f"Seasonal pattern detected (period={seasonality.period})")
        else:
            parts.append("No seasonality detected")

        return ". ".join(parts) + "."

    @staticmethod
    def _period_name(period: int, period_label: str) -> str:
        if period_label == "day":
            if period == 7:
                return "weekly"
            if period in (28, 30):
                return "monthly"
            if period == 14:
                return "bi-weekly"
        if period_label == "month":
            if period == 12:
                return "yearly"
            if period == 4:
                return "quarterly"
        return f"{period}-{period_label}"
