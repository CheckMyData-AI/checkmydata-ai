"""Cases, scoring and the release gate for the routing eval (PRJ-13 T08a).

Kept free of I/O beyond reading the case and recording files, so the CI tier is pure and
the live tier (`run.py`) is a thin loop around it.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.agents.router import RouteResult, _parse_route_response

SEED_CASES = Path(__file__).with_name("seed_cases.jsonl")
RECORDINGS = Path(__file__).with_name("recordings.jsonl")
BASELINE = Path(__file__).with_name("baseline.json")

#: The CI gate: routing accuracy may not drop by more than this many points against the
#: committed baseline (PRJ-13 acceptance: "CI fails on a routing-accuracy drop > 5 points").
MAX_DROP_POINTS = 5.0

_CAPS = {"db", "kb", "repo", "mcp", "analytics"}


class CaseError(ValueError):
    """A case or recording that cannot be scored — a TEST_ERROR, never a behaviour fail."""


@dataclass(frozen=True)
class RoutingCase:
    id: str
    question: str
    caps: frozenset[str]
    routes: frozenset[str]
    pipeline: bool | None
    kind: str
    provenance: str

    @property
    def capability_flags(self) -> dict[str, bool]:
        return {
            "has_connection": "db" in self.caps,
            "has_knowledge_base": "kb" in self.caps,
            "has_repo": "repo" in self.caps,
            "has_mcp_sources": "mcp" in self.caps,
            "has_analytics_sources": "analytics" in self.caps,
        }


def _parse_caps(raw: str) -> frozenset[str]:
    if raw == "none":
        return frozenset()
    caps = frozenset(raw.split("+"))
    unknown = caps - _CAPS
    if unknown:
        raise CaseError(f"unknown capabilities {sorted(unknown)}")
    return caps


def load_cases(path: Path = SEED_CASES) -> list[RoutingCase]:
    cases: list[RoutingCase] = []
    seen: set[str] = set()
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            case = RoutingCase(
                id=row["id"],
                question=row["question"],
                caps=_parse_caps(row["caps"]),
                routes=frozenset(row["routes"]),
                pipeline=row.get("pipeline"),
                kind=row["kind"],
                provenance=row["provenance"],
            )
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise CaseError(f"{path.name}:{n}: {exc}") from exc
        if case.id in seen:
            raise CaseError(f"{path.name}:{n}: duplicate id {case.id}")
        if not case.routes:
            raise CaseError(f"{path.name}:{n}: {case.id} names no acceptable route")
        seen.add(case.id)
        cases.append(case)
    return cases


def route_from_raw(case: RoutingCase, raw: str) -> RouteResult:
    """The production parser and capability guards applied to a recorded model reply."""
    return _parse_route_response(raw, **case.capability_flags)


@dataclass
class CaseOutcome:
    case_id: str
    route: str
    route_ok: bool
    pipeline_ok: bool | None
    defaulted: bool


@dataclass
class Report:
    outcomes: list[CaseOutcome] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.outcomes)

    @property
    def accuracy(self) -> float:
        return 100.0 * sum(o.route_ok for o in self.outcomes) / self.n if self.n else 0.0

    @property
    def pipeline_accuracy(self) -> float | None:
        judged = [o.pipeline_ok for o in self.outcomes if o.pipeline_ok is not None]
        return 100.0 * sum(judged) / len(judged) if judged else None

    @property
    def default_rate(self) -> float:
        """How often the router fell back to its default — a parse failure or an error."""
        return 100.0 * sum(o.defaulted for o in self.outcomes) / self.n if self.n else 0.0

    def interval(self, z: float = 1.96) -> tuple[float, float]:
        """Wilson score interval for the route accuracy, in points."""
        if not self.n:
            return (0.0, 0.0)
        p = sum(o.route_ok for o in self.outcomes) / self.n
        denom = 1 + z * z / self.n
        centre = (p + z * z / (2 * self.n)) / denom
        half = z * math.sqrt(p * (1 - p) / self.n + z * z / (4 * self.n * self.n)) / denom
        return (100.0 * (centre - half), 100.0 * (centre + half))

    def confusion(self) -> Counter:
        return Counter(o.route for o in self.outcomes if not o.route_ok)

    def to_dict(self) -> dict:
        lo, hi = self.interval()
        return {
            "n": self.n,
            "accuracy": round(self.accuracy, 2),
            "interval_95": [round(lo, 2), round(hi, 2)],
            "pipeline_accuracy": None
            if self.pipeline_accuracy is None
            else round(self.pipeline_accuracy, 2),
            "default_rate": round(self.default_rate, 2),
            "wrong_routes": dict(self.confusion()),
            "failed_cases": sorted({o.case_id for o in self.outcomes if not o.route_ok}),
            "errors": self.errors,
        }


def score(case: RoutingCase, result: RouteResult) -> CaseOutcome:
    from app.agents.router import _DEFAULT_ROUTE

    defaulted = result.raw is None and result.approach == _DEFAULT_ROUTE.approach
    pipeline_ok = None if case.pipeline is None else result.use_complex_pipeline == case.pipeline
    return CaseOutcome(
        case_id=case.id,
        route=result.route,
        # A fallback is the ABSENCE of a decision, and it happens to be `explore` — which
        # several cases accept. Counting it would score a broken router as a right one
        # (measured on the first live run: 1 of 90 replies was unparseable and landed
        # on `explore`). So a defaulted outcome is never correct, whatever it matches.
        route_ok=result.route in case.routes and not defaulted,
        pipeline_ok=None if defaulted else pipeline_ok,
        defaulted=defaulted,
    )


def replay(cases: list[RoutingCase], recordings_path: Path = RECORDINGS) -> Report:
    """Score every recorded reply for every case. Deterministic; the CI tier."""
    by_case: dict[str, list[str]] = {}
    for n, line in enumerate(recordings_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            by_case.setdefault(row["case_id"], []).append(row["raw"])
        except (KeyError, json.JSONDecodeError) as exc:
            raise CaseError(f"{recordings_path.name}:{n}: {exc}") from exc
    report = Report()
    for case in cases:
        raws = by_case.get(case.id)
        if not raws:
            report.errors.append(f"{case.id}: no recording")
            continue
        for raw in raws:
            report.outcomes.append(score(case, route_from_raw(case, raw)))
    return report


def gate(report: Report, baseline: dict, max_drop: float = MAX_DROP_POINTS) -> list[str]:
    """Reasons the release gate refuses this report; empty means it passes.

    A drop beyond `max_drop` points fails even when the interval overlaps the baseline:
    the recordings are fixed, so a replay's difference is a code change, not sampling noise.
    """
    reasons: list[str] = []
    if report.errors:
        reasons.append(f"{len(report.errors)} case(s) could not be scored: {report.errors[:3]}")
    drop = float(baseline["accuracy"]) - report.accuracy
    if drop > max_drop:
        reasons.append(
            f"routing accuracy {report.accuracy:.1f} is {drop:.1f} points below the baseline "
            f"{baseline['accuracy']} (limit {max_drop})"
        )
    return reasons
