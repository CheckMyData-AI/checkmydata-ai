"""Loss Detector — finds revenue leaks, inefficient spend, and conversion drops.

Generates "loss" insights with:
- Funnel drop-offs (where users/revenue are lost)
- Spend inefficiency (channels with poor ROI)
- Revenue regression (declines vs benchmarks)
- Monetary quantification ("~$X/month lost due to Y")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LossReport:
    """A detected loss with quantification and fix suggestion."""

    loss_type: str
    title: str
    description: str
    metric: str
    current_value: float
    expected_value: float
    loss_amount: float
    loss_pct: float
    estimated_monthly_impact: str
    suggested_fix: str
    confidence: float = 0.5
    evidence: list[str] = field(default_factory=list)
    severity: str = "warning"

    def to_dict(self) -> dict[str, Any]:
        return {
            "loss_type": self.loss_type,
            "title": self.title,
            "description": self.description,
            "metric": self.metric,
            "current_value": round(self.current_value, 2),
            "expected_value": round(self.expected_value, 2),
            "loss_amount": round(self.loss_amount, 2),
            "loss_pct": round(self.loss_pct, 1),
            "estimated_monthly_impact": self.estimated_monthly_impact,
            "suggested_fix": self.suggested_fix,
            "confidence": round(self.confidence, 2),
            "evidence": self.evidence,
            "severity": self.severity,
        }


class LossDetector:
    """Analyze tabular data to find revenue leaks and conversion drops."""

    DROP_THRESHOLD_PCT = 15.0
    INEFFICIENCY_THRESHOLD = 0.5

    def analyze(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        *,
        question: str = "",
        table_name: str = "",
    ) -> list[LossReport]:
        """Run all loss detection heuristics on the data."""
        if not rows or not columns:
            return []

        losses: list[LossReport] = []

        losses.extend(self._detect_funnel_drops(rows, columns, table_name))
        losses.extend(self._detect_spend_inefficiency(rows, columns, table_name))
        losses.extend(self._detect_revenue_regression(rows, columns, table_name))
        losses.extend(self._detect_high_churn_segments(rows, columns, table_name))

        losses.sort(key=lambda x: abs(x.loss_pct), reverse=True)
        return losses

    def _detect_funnel_drops(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        table_name: str,
    ) -> list[LossReport]:
        """Detect steps where conversion drops significantly."""
        losses: list[LossReport] = []

        step_hints = (
            "step",
            "stage",
            "funnel",
            "phase",
            "status",
        )
        step_col = None
        for col in columns:
            if any(h in col.lower() for h in step_hints):
                step_col = col
                break

        count_cols = [
            c
            for c in columns
            if any(h in c.lower() for h in ("count", "users", "sessions", "visits", "conversions"))
        ]

        if not step_col or not count_cols:
            return losses

        for cnt_col in count_cols:
            ordered: list[dict[str, Any]] = []
            for r in rows:
                val = self._to_number(r.get(cnt_col))
                step = r.get(step_col)
                if val is not None and step is not None:
                    ordered.append({"step": str(step), "value": val})

            if len(ordered) < 2:
                continue

            for i in range(1, len(ordered)):
                prev_val = float(ordered[i - 1]["value"])
                curr_val = float(ordered[i]["value"])
                if prev_val > 0:
                    drop_pct = ((prev_val - curr_val) / prev_val) * 100
                    if drop_pct > self.DROP_THRESHOLD_PCT:
                        losses.append(
                            LossReport(
                                loss_type="funnel_drop",
                                title=(
                                    f"Funnel drop: {ordered[i - 1]['step']} → {ordered[i]['step']}"
                                ),
                                description=(
                                    f"{cnt_col} drops {drop_pct:.0f}% "
                                    f"from '{ordered[i - 1]['step']}' "
                                    f"({prev_val:,.0f}) to "
                                    f"'{ordered[i]['step']}' "
                                    f"({curr_val:,.0f})."
                                ),
                                metric=cnt_col,
                                current_value=curr_val,
                                expected_value=prev_val,
                                loss_amount=prev_val - curr_val,
                                loss_pct=round(drop_pct, 1),
                                estimated_monthly_impact=(
                                    f"~{prev_val - curr_val:,.0f} {cnt_col} lost at this step"
                                ),
                                suggested_fix=(
                                    f"Investigate the "
                                    f"'{ordered[i]['step']}' step. "
                                    "Common fixes: simplify the "
                                    "flow, reduce friction, add "
                                    "trust signals."
                                ),
                                confidence=self._calc_confidence(len(rows), drop_pct),
                                evidence=[
                                    f"Before: {prev_val:,.0f}",
                                    f"After: {curr_val:,.0f}",
                                    f"Drop: {drop_pct:.1f}%",
                                ],
                                severity=("critical" if drop_pct > 50 else "warning"),
                            )
                        )

        return losses

    def _detect_spend_inefficiency(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        table_name: str,
    ) -> list[LossReport]:
        """Find channels/campaigns with poor ROI."""
        losses: list[LossReport] = []

        spend_cols = [
            c
            for c in columns
            if any(h in c.lower() for h in ("spend", "cost", "budget", "investment", "ad_spend"))
        ]
        revenue_cols = [
            c
            for c in columns
            if any(h in c.lower() for h in ("revenue", "sales", "income", "return", "roas"))
        ]
        segment_cols = [
            c
            for c in columns
            if any(
                h in c.lower()
                for h in (
                    "channel",
                    "campaign",
                    "source",
                    "medium",
                    "platform",
                    "ad_group",
                )
            )
        ]

        if not spend_cols or not revenue_cols:
            return losses

        for spend_col in spend_cols:
            for rev_col in revenue_cols:
                total_spend = 0.0
                total_rev = 0.0
                segment_data: list[dict[str, Any]] = []

                for r in rows:
                    s = self._to_number(r.get(spend_col))
                    rev = self._to_number(r.get(rev_col))
                    if s is not None and rev is not None and s > 0:
                        roi = rev / s
                        seg_name = ""
                        for sc in segment_cols:
                            if r.get(sc):
                                seg_name = str(r[sc])
                                break
                        segment_data.append(
                            {"row": r, "spend": s, "revenue": rev, "roi": roi, "name": seg_name}
                        )
                        total_spend += s
                        total_rev += rev

                if not segment_data or total_spend == 0:
                    continue

                avg_roi = total_rev / total_spend

                for seg in segment_data:
                    if (
                        seg["roi"] < avg_roi * self.INEFFICIENCY_THRESHOLD
                        and seg["spend"] > total_spend * 0.05
                    ):
                        wasted = seg["spend"] - seg["revenue"]
                        loss_pct = ((avg_roi - seg["roi"]) / avg_roi) * 100
                        name = seg["name"] or "segment"
                        losses.append(
                            LossReport(
                                loss_type="spend_inefficiency",
                                title=(f"Inefficient spend: {name}"),
                                description=(
                                    f"'{name}' has ROI of "
                                    f"{seg['roi']:.2f}x vs average "
                                    f"{avg_roi:.2f}x. Spending "
                                    f"{seg['spend']:,.0f} for only "
                                    f"{seg['revenue']:,.0f} return."
                                ),
                                metric=spend_col,
                                current_value=seg["roi"],
                                expected_value=avg_roi,
                                loss_amount=max(0.0, wasted),
                                loss_pct=round(loss_pct, 1),
                                estimated_monthly_impact=(f"~{max(0, wasted):,.0f} wasted spend"),
                                suggested_fix=(
                                    f"Reallocate budget from "
                                    f"'{name}' to higher-ROI "
                                    "channels, or optimize the "
                                    "targeting/creative."
                                ),
                                confidence=self._calc_confidence(len(segment_data), loss_pct),
                                evidence=[
                                    f"ROI: {seg['roi']:.2f}x",
                                    f"Avg ROI: {avg_roi:.2f}x",
                                    f"Spend: {seg['spend']:,.0f}",
                                    f"Revenue: {seg['revenue']:,.0f}",
                                ],
                                severity=("critical" if wasted > total_spend * 0.1 else "warning"),
                            )
                        )

        return losses[:5]

    def _detect_revenue_regression(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        table_name: str,
    ) -> list[LossReport]:
        """Detect declining trends in revenue/conversion metrics."""
        losses: list[LossReport] = []

        value_cols = [
            c
            for c in columns
            if any(
                h in c.lower()
                for h in (
                    "revenue",
                    "sales",
                    "conversion",
                    "orders",
                    "subscribers",
                    "mrr",
                    "arr",
                )
            )
        ]

        time_cols = [
            c
            for c in columns
            if any(
                h in c.lower()
                for h in (
                    "date",
                    "month",
                    "week",
                    "period",
                    "day",
                    "year",
                    "quarter",
                )
            )
        ]

        for val_col in value_cols:
            values = self._extract_numeric(rows, val_col)
            if len(values) < 3:
                continue

            first_half = values[: len(values) // 2]
            second_half = values[len(values) // 2 :]

            avg_first = sum(first_half) / len(first_half) if first_half else 0
            avg_second = sum(second_half) / len(second_half) if second_half else 0

            if avg_first > 0:
                decline_pct = ((avg_first - avg_second) / avg_first) * 100
                if decline_pct > self.DROP_THRESHOLD_PCT:
                    period_label = ""
                    if time_cols:
                        first_time = str(rows[0].get(time_cols[0], ""))
                        last_time = str(rows[-1].get(time_cols[0], ""))
                        if first_time and last_time:
                            period_label = f" ({first_time} → {last_time})"

                    losses.append(
                        LossReport(
                            loss_type="revenue_regression",
                            title=(f"Declining {val_col}{period_label}"),
                            description=(
                                f"{val_col} dropped {decline_pct:.0f}% "
                                f"from average {avg_first:,.2f} "
                                f"to {avg_second:,.2f}."
                            ),
                            metric=val_col,
                            current_value=avg_second,
                            expected_value=avg_first,
                            loss_amount=avg_first - avg_second,
                            loss_pct=round(decline_pct, 1),
                            estimated_monthly_impact=(
                                f"~{avg_first - avg_second:,.2f} decline in {val_col} per period"
                            ),
                            suggested_fix=(
                                "Investigate what changed during "
                                "the decline period. Check for "
                                "product changes, market shifts, "
                                "or data issues."
                            ),
                            confidence=self._calc_confidence(len(values), decline_pct),
                            evidence=[
                                f"Earlier avg: {avg_first:,.2f}",
                                f"Recent avg: {avg_second:,.2f}",
                                f"Decline: {decline_pct:.1f}%",
                                f"Data points: {len(values)}",
                            ],
                            severity=("critical" if decline_pct > 40 else "warning"),
                        )
                    )

        return losses

    def _detect_high_churn_segments(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        table_name: str,
    ) -> list[LossReport]:
        """Find segments with high churn or cancellation rates."""
        losses: list[LossReport] = []

        churn_cols = [
            c
            for c in columns
            if any(
                h in c.lower()
                for h in (
                    "churn",
                    "cancel",
                    "refund",
                    "return",
                    "bounce",
                    "drop",
                    "lost",
                    "inactive",
                )
            )
        ]

        if not churn_cols:
            return losses

        segment_cols = [
            c
            for c in columns
            if any(
                h in c.lower()
                for h in (
                    "segment",
                    "plan",
                    "tier",
                    "country",
                    "channel",
                    "category",
                    "type",
                    "source",
                )
            )
        ]

        for churn_col in churn_cols:
            values = self._extract_numeric(rows, churn_col)
            if len(values) < 2:
                continue

            avg = sum(values) / len(values)
            if avg == 0:
                continue

            for r in rows:
                val = self._to_number(r.get(churn_col))
                if val is None:
                    continue

                excess = ((val - avg) / avg) * 100 if avg > 0 else 0
                if excess > self.DROP_THRESHOLD_PCT:
                    seg_label = ""
                    for sc in segment_cols:
                        if r.get(sc):
                            seg_label = str(r[sc])
                            break

                    if not seg_label:
                        seg_label = str(list(r.values())[:1])

                    losses.append(
                        LossReport(
                            loss_type="high_churn",
                            title=(f"High {churn_col}: {seg_label}"),
                            description=(
                                f"'{seg_label}' has {churn_col} "
                                f"of {val:,.2f}, which is "
                                f"{excess:.0f}% above average "
                                f"({avg:,.2f})."
                            ),
                            metric=churn_col,
                            current_value=val,
                            expected_value=avg,
                            loss_amount=val - avg,
                            loss_pct=round(excess, 1),
                            estimated_monthly_impact=(
                                f"Reducing {churn_col} for "
                                f"'{seg_label}' to average "
                                "could recover lost users."
                            ),
                            suggested_fix=(
                                f"Investigate why '{seg_label}' "
                                f"has elevated {churn_col}. "
                                "Check onboarding, product "
                                "experience, or pricing."
                            ),
                            confidence=self._calc_confidence(len(values), excess),
                            evidence=[
                                f"Value: {val:,.2f}",
                                f"Average: {avg:,.2f}",
                                f"Excess: {excess:.1f}%",
                            ],
                            severity=("critical" if excess > 50 else "warning"),
                        )
                    )

        return losses[:5]

    @staticmethod
    def _extract_numeric(rows: list[dict[str, Any]], col: str) -> list[float]:
        result: list[float] = []
        for r in rows:
            val = r.get(col)
            if isinstance(val, (int, float)) and val == val:
                result.append(float(val))
        return result

    @staticmethod
    def _to_number(val: Any) -> float | None:
        if isinstance(val, (int, float)) and val == val:
            return float(val)
        return None

    @staticmethod
    def _calc_confidence(sample_size: int, magnitude: float) -> float:
        base = 0.4
        if sample_size >= 100:
            base += 0.2
        elif sample_size >= 20:
            base += 0.15
        elif sample_size >= 5:
            base += 0.1
        if abs(magnitude) > 50:
            base += 0.15
        elif abs(magnitude) > 25:
            base += 0.1
        return min(0.9, base)

    def format_losses(self, losses: list[LossReport]) -> str:
        """Format loss reports as markdown text for chat display."""
        if not losses:
            return ""

        lines = ["\n🩸 LOSS REPORT:"]
        for loss in losses:
            icon = {
                "funnel_drop": "📉",
                "spend_inefficiency": "💸",
                "revenue_regression": "📊",
                "high_churn": "🚪",
            }.get(loss.loss_type, "⚠️")

            lines.append(f"\n  {icon} **{loss.title}**")
            lines.append(f"     {loss.description}")
            if loss.estimated_monthly_impact:
                lines.append(f"     💰 Impact: {loss.estimated_monthly_impact}")
            if loss.suggested_fix:
                lines.append(f"     → Fix: {loss.suggested_fix}")
        return "\n".join(lines)
