"""Opportunity Detector — finds growth segments, undermonetized users,
and high-potential channels by analyzing query result data.

Generates "opportunity" insights with:
- Segment comparison (which cohorts outperform)
- Gap analysis (where untapped potential exists)
- Impact estimates (expected revenue/conversion lift)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Opportunity:
    """A discovered growth opportunity with evidence and impact estimate."""

    opportunity_type: str
    title: str
    description: str
    segment: str
    metric: str
    current_value: float
    benchmark_value: float
    gap_pct: float
    estimated_impact: str
    suggested_action: str
    confidence: float = 0.5
    evidence: list[str] = field(default_factory=list)
    severity: str = "positive"

    def to_dict(self) -> dict[str, Any]:
        return {
            "opportunity_type": self.opportunity_type,
            "title": self.title,
            "description": self.description,
            "segment": self.segment,
            "metric": self.metric,
            "current_value": round(self.current_value, 2),
            "benchmark_value": round(self.benchmark_value, 2),
            "gap_pct": round(self.gap_pct, 1),
            "estimated_impact": self.estimated_impact,
            "suggested_action": self.suggested_action,
            "confidence": round(self.confidence, 2),
            "evidence": self.evidence,
            "severity": self.severity,
        }


class OpportunityDetector:
    """Analyze tabular data to find growth opportunities."""

    MIN_SEGMENT_ROWS = 3
    OUTPERFORM_THRESHOLD_PCT = 30.0
    UNDERPERFORM_THRESHOLD_PCT = -20.0

    def analyze(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        *,
        question: str = "",
        table_name: str = "",
    ) -> list[Opportunity]:
        """Run all opportunity detection heuristics on the data."""
        if not rows or not columns:
            return []

        opportunities: list[Opportunity] = []

        opportunities.extend(self._detect_high_performers(rows, columns, table_name))
        opportunities.extend(self._detect_conversion_gaps(rows, columns, table_name))
        opportunities.extend(self._detect_undermonetized_segments(rows, columns, table_name))
        opportunities.extend(self._detect_growth_potential(rows, columns, table_name))

        opportunities.sort(key=lambda o: abs(o.gap_pct), reverse=True)
        return opportunities

    def _detect_high_performers(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        table_name: str,
    ) -> list[Opportunity]:
        """Find segments that significantly outperform the average."""
        opportunities: list[Opportunity] = []
        segment_cols = self._find_segment_columns(rows, columns)
        value_cols = self._find_value_columns(columns)

        for seg_col in segment_cols:
            for val_col in value_cols:
                opps = self._compare_segments(rows, seg_col, val_col, table_name)
                opportunities.extend(opps)

        return opportunities

    def _detect_conversion_gaps(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        table_name: str,
    ) -> list[Opportunity]:
        """Find columns with conversion/rate patterns that show gaps."""
        opportunities: list[Opportunity] = []
        rate_cols = [
            c
            for c in columns
            if any(
                h in c.lower()
                for h in (
                    "rate",
                    "conversion",
                    "ctr",
                    "ratio",
                    "percent",
                    "pct",
                )
            )
        ]

        for col in rate_cols:
            values = self._extract_numeric(rows, col)
            if len(values) < self.MIN_SEGMENT_ROWS:
                continue

            avg = sum(values) / len(values)
            if avg == 0:
                continue

            best = max(values)
            worst = min(values)

            if best > 0 and worst > 0:
                gap = ((best - worst) / avg) * 100
                if gap > self.OUTPERFORM_THRESHOLD_PCT:
                    opportunities.append(
                        Opportunity(
                            opportunity_type="conversion_gap",
                            title=(f"Conversion gap in {col}: {worst:.1f}% to {best:.1f}%"),
                            description=(
                                f"The range in '{col}' shows a "
                                f"{gap:.0f}% spread. Bringing low "
                                "performers to average could yield "
                                "significant improvement."
                            ),
                            segment=table_name or "query_result",
                            metric=col,
                            current_value=worst,
                            benchmark_value=avg,
                            gap_pct=round(gap, 1),
                            estimated_impact=(
                                f"Closing this gap could improve "
                                f"overall {col} by "
                                f"~{gap / len(values):.1f}%"
                            ),
                            suggested_action=(
                                f"Investigate why some segments "
                                f"have low {col} and optimize "
                                "their funnel."
                            ),
                            confidence=self._calc_confidence(len(values), gap),
                            evidence=[
                                f"Best: {best:.2f}",
                                f"Worst: {worst:.2f}",
                                f"Average: {avg:.2f}",
                                f"Rows analyzed: {len(values)}",
                            ],
                        )
                    )

        return opportunities

    def _detect_undermonetized_segments(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        table_name: str,
    ) -> list[Opportunity]:
        """Find segments with high volume but low value metrics."""
        opportunities: list[Opportunity] = []
        volume_cols = [
            c
            for c in columns
            if any(
                h in c.lower()
                for h in (
                    "count",
                    "users",
                    "visits",
                    "sessions",
                    "traffic",
                    "views",
                    "impressions",
                )
            )
        ]
        value_cols = [
            c
            for c in columns
            if any(
                h in c.lower()
                for h in (
                    "revenue",
                    "sales",
                    "amount",
                    "profit",
                    "arpu",
                    "ltv",
                    "aov",
                    "spend",
                )
            )
        ]

        if not volume_cols or not value_cols:
            return opportunities

        for vol_col in volume_cols:
            for val_col in value_cols:
                vol_values = self._extract_numeric(rows, vol_col)
                val_values = self._extract_numeric(rows, val_col)

                if (
                    len(vol_values) < self.MIN_SEGMENT_ROWS
                    or len(val_values) < self.MIN_SEGMENT_ROWS
                ):
                    continue

                per_unit: list[dict[str, Any]] = []
                for r in rows:
                    vol = self._to_number(r.get(vol_col))
                    val = self._to_number(r.get(val_col))
                    if vol is not None and val is not None and vol > 0:
                        per_unit.append({"row": r, "value_per_unit": val / vol})

                if len(per_unit) < self.MIN_SEGMENT_ROWS:
                    continue

                avg_per_unit = sum(p["value_per_unit"] for p in per_unit) / len(per_unit)

                for entry in per_unit:
                    ratio = float(entry["value_per_unit"])
                    if avg_per_unit > 0:
                        gap = (ratio - avg_per_unit) / avg_per_unit * 100
                        if gap < self.UNDERPERFORM_THRESHOLD_PCT:
                            seg_label = self._describe_row(entry["row"], columns)
                            opportunities.append(
                                Opportunity(
                                    opportunity_type="undermonetized",
                                    title=(f"Undermonetized: {seg_label}"),
                                    description=(
                                        f"{seg_label} has high "
                                        f"{vol_col} but low "
                                        f"{val_col} per unit "
                                        f"({ratio:.2f} vs avg "
                                        f"{avg_per_unit:.2f})."
                                    ),
                                    segment=seg_label,
                                    metric=val_col,
                                    current_value=ratio,
                                    benchmark_value=avg_per_unit,
                                    gap_pct=round(gap, 1),
                                    estimated_impact=(
                                        "Improving monetization to "
                                        "average would increase "
                                        f"{val_col} by "
                                        f"~{abs(gap):.0f}% for "
                                        "this segment."
                                    ),
                                    suggested_action=(
                                        f"Analyze {seg_label}'s "
                                        "user journey to find "
                                        "monetization blockers."
                                    ),
                                    confidence=self._calc_confidence(len(per_unit), abs(gap)),
                                    evidence=[
                                        f"Value per unit: {ratio:.2f}",
                                        f"Average: {avg_per_unit:.2f}",
                                        f"Gap: {gap:.1f}%",
                                    ],
                                )
                            )

        return opportunities[:5]

    def _detect_growth_potential(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        table_name: str,
    ) -> list[Opportunity]:
        """Find segments with strong metrics but low volume — scale candidates."""
        opportunities: list[Opportunity] = []
        segment_cols = self._find_segment_columns(rows, columns)
        value_cols = self._find_value_columns(columns)
        volume_cols = [
            c
            for c in columns
            if any(
                h in c.lower()
                for h in (
                    "count",
                    "users",
                    "traffic",
                    "sessions",
                    "visits",
                )
            )
        ]

        if not segment_cols or not value_cols or not volume_cols:
            return opportunities

        for seg_col in segment_cols:
            for val_col in value_cols:
                for vol_col in volume_cols:
                    opps = self._find_scale_candidates(
                        rows,
                        seg_col,
                        val_col,
                        vol_col,
                        table_name,
                    )
                    opportunities.extend(opps)

        return opportunities[:5]

    def _find_scale_candidates(
        self,
        rows: list[dict[str, Any]],
        seg_col: str,
        val_col: str,
        vol_col: str,
        table_name: str,
    ) -> list[Opportunity]:
        """Identify segments with high value but low volume."""
        segments: dict[str, dict[str, float]] = {}
        for r in rows:
            seg = str(r.get(seg_col, ""))
            if not seg:
                continue
            val = self._to_number(r.get(val_col))
            vol = self._to_number(r.get(vol_col))
            if val is not None and vol is not None:
                if seg not in segments:
                    segments[seg] = {"value": 0, "volume": 0, "count": 0}
                segments[seg]["value"] += val
                segments[seg]["volume"] += vol
                segments[seg]["count"] += 1

        if len(segments) < 2:
            return []

        total_vol = sum(s["volume"] for s in segments.values())
        total_val = sum(s["value"] for s in segments.values())

        if total_vol == 0 or total_val == 0:
            return []

        opportunities: list[Opportunity] = []
        for seg_name, data in segments.items():
            vol_share = data["volume"] / total_vol * 100
            val_share = data["value"] / total_val * 100

            if val_share > vol_share * 1.5 and vol_share < 20:
                gap = val_share - vol_share
                opportunities.append(
                    Opportunity(
                        opportunity_type="growth_potential",
                        title=(f"High-potential segment: {seg_name}"),
                        description=(
                            f"'{seg_name}' has {val_share:.1f}% "
                            f"of {val_col} but only "
                            f"{vol_share:.1f}% of {vol_col}. "
                            "Scaling volume here could yield "
                            "outsized returns."
                        ),
                        segment=seg_name,
                        metric=val_col,
                        current_value=vol_share,
                        benchmark_value=val_share,
                        gap_pct=round(gap, 1),
                        estimated_impact=(
                            f"Doubling {vol_col} for "
                            f"'{seg_name}' could increase "
                            f"total {val_col} by "
                            f"~{val_share:.1f}%."
                        ),
                        suggested_action=(
                            f"Increase {vol_col} to "
                            f"'{seg_name}' through targeted "
                            "campaigns or expansion."
                        ),
                        confidence=self._calc_confidence(int(data["count"]), gap),
                        evidence=[
                            f"Value share: {val_share:.1f}%",
                            f"Volume share: {vol_share:.1f}%",
                            f"Efficiency ratio: {val_share / max(vol_share, 0.1):.1f}x",
                        ],
                    )
                )

        return opportunities

    def _compare_segments(
        self,
        rows: list[dict[str, Any]],
        seg_col: str,
        val_col: str,
        table_name: str,
    ) -> list[Opportunity]:
        """Compare segment performance against the overall average."""
        segments: dict[str, list[float]] = {}
        for r in rows:
            seg = str(r.get(seg_col, ""))
            val = self._to_number(r.get(val_col))
            if seg and val is not None:
                segments.setdefault(seg, []).append(val)

        if len(segments) < 2:
            return []

        all_values = [v for vals in segments.values() for v in vals]
        if not all_values:
            return []

        overall_avg = sum(all_values) / len(all_values)
        if overall_avg == 0:
            return []

        opportunities: list[Opportunity] = []
        for seg_name, values in segments.items():
            if len(values) < self.MIN_SEGMENT_ROWS:
                continue

            seg_avg = sum(values) / len(values)
            gap_pct = ((seg_avg - overall_avg) / overall_avg) * 100

            if gap_pct > self.OUTPERFORM_THRESHOLD_PCT:
                opportunities.append(
                    Opportunity(
                        opportunity_type="high_performer",
                        title=(f"'{seg_name}' outperforms by {gap_pct:.0f}% on {val_col}"),
                        description=(
                            f"Segment '{seg_name}' averages "
                            f"{seg_avg:.2f} on {val_col}, "
                            f"which is {gap_pct:.0f}% above "
                            f"the overall average of "
                            f"{overall_avg:.2f}."
                        ),
                        segment=seg_name,
                        metric=val_col,
                        current_value=seg_avg,
                        benchmark_value=overall_avg,
                        gap_pct=round(gap_pct, 1),
                        estimated_impact=(
                            f"Scaling '{seg_name}' could leverage this performance advantage."
                        ),
                        suggested_action=(
                            f"Investigate what makes "
                            f"'{seg_name}' successful and "
                            "replicate the pattern."
                        ),
                        confidence=self._calc_confidence(len(values), gap_pct),
                        evidence=[
                            f"Segment avg: {seg_avg:.2f}",
                            f"Overall avg: {overall_avg:.2f}",
                            f"Sample: {len(values)} rows",
                        ],
                    )
                )

        return opportunities

    def _find_segment_columns(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
    ) -> list[str]:
        """Identify columns likely to be categorical segments."""
        segment_hints = (
            "country",
            "region",
            "city",
            "channel",
            "source",
            "medium",
            "campaign",
            "segment",
            "category",
            "type",
            "plan",
            "tier",
            "group",
            "status",
            "platform",
            "device",
            "os",
            "browser",
            "age",
            "gender",
        )
        candidates: list[str] = []
        for col in columns:
            if any(h in col.lower() for h in segment_hints):
                candidates.append(col)
                continue
            values = [r.get(col) for r in rows[:50] if r.get(col) is not None]
            if values and all(isinstance(v, str) for v in values):
                unique = len(set(values))
                if 2 <= unique <= 50:
                    candidates.append(col)
        return candidates[:5]

    def _find_value_columns(self, columns: list[str]) -> list[str]:
        """Identify columns likely to hold value metrics."""
        value_hints = (
            "revenue",
            "sales",
            "amount",
            "profit",
            "price",
            "ltv",
            "arpu",
            "aov",
            "conversion",
            "rate",
            "ctr",
            "roas",
            "roi",
            "spend",
            "cost",
            "total",
        )
        return [c for c in columns if any(h in c.lower() for h in value_hints)][:5]

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
    def _calc_confidence(sample_size: int, gap_magnitude: float) -> float:
        base = 0.4
        if sample_size >= 100:
            base += 0.2
        elif sample_size >= 20:
            base += 0.15
        elif sample_size >= 5:
            base += 0.1

        if abs(gap_magnitude) > 100:
            base += 0.15
        elif abs(gap_magnitude) > 50:
            base += 0.1
        elif abs(gap_magnitude) > 30:
            base += 0.05

        return min(0.9, base)

    @staticmethod
    def _describe_row(row: dict[str, Any], columns: list[str]) -> str:
        """Create a human label for a row using its first string column."""
        for col in columns:
            val = row.get(col)
            if isinstance(val, str) and val:
                return val
        return str(list(row.values())[:2])

    def format_opportunities(self, opportunities: list[Opportunity]) -> str:
        """Format opportunities as markdown text for chat display."""
        if not opportunities:
            return ""

        lines = ["\n💰 OPPORTUNITY REPORT:"]
        for opp in opportunities:
            icon = {
                "high_performer": "🏆",
                "conversion_gap": "📈",
                "undermonetized": "💎",
                "growth_potential": "🚀",
            }.get(opp.opportunity_type, "💡")

            lines.append(f"\n  {icon} **{opp.title}**")
            lines.append(f"     {opp.description}")
            if opp.estimated_impact:
                lines.append(f"     📊 Impact: {opp.estimated_impact}")
            if opp.suggested_action:
                lines.append(f"     → Action: {opp.suggested_action}")
        return "\n".join(lines)
