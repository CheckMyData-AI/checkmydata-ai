"""Cases, scoring and the release gate for the result-gate eval (PRJ-13 T08b)."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agents.data_gate import DataGate
from app.agents.result_validation import ResultValidation
from app.agents.validation import AgentResultValidator
from app.connectors.base import QueryResult

CASES = Path(__file__).with_name("cases.jsonl")
ACTIONS = ("accept", "warn", "requery", "block")


class CaseError(ValueError):
    """A case that cannot be scored — a TEST_ERROR, never a verdict."""


@dataclass(frozen=True)
class GateCase:
    id: str
    qr: QueryResult
    expect: str
    requires: dict[str, Any]
    note: str


def load_cases(path: Path = CASES) -> list[GateCase]:
    cases: list[GateCase] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if row["expect"] not in ACTIONS:
                raise CaseError(f"{path.name}:{n}: unknown action {row['expect']!r}")
            qr = QueryResult(
                columns=row["columns"],
                rows=row["rows"],
                row_count=len(row["rows"]),
                truncated=bool(row.get("truncated", False)),
                error=row.get("error"),
            )
            cases.append(
                GateCase(row["id"], qr, row["expect"], row.get("requires", {}), row["note"])
            )
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise CaseError(f"{path.name}:{n}: {exc}") from exc
    return cases


@dataclass
class GateReport:
    pairs: list[tuple[str, str, str]] = field(default_factory=list)  # (id, expected, got)
    skipped: list[str] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return (
            100.0 * sum(e == g for _, e, g in self.pairs) / len(self.pairs) if self.pairs else 0.0
        )

    def precision(self, action: str) -> float | None:
        predicted = [(e, g) for _, e, g in self.pairs if g == action]
        return 100.0 * sum(e == g for e, g in predicted) / len(predicted) if predicted else None

    def recall(self, action: str) -> float | None:
        actual = [(e, g) for _, e, g in self.pairs if e == action]
        return 100.0 * sum(e == g for e, g in actual) / len(actual) if actual else None

    def confusion(self) -> Counter:
        return Counter((e, g) for _, e, g in self.pairs if e != g)

    def to_dict(self) -> dict:
        return {
            "n": len(self.pairs),
            "accuracy": round(self.accuracy, 2),
            "precision": {a: self.precision(a) for a in ACTIONS},
            "recall": {a: self.recall(a) for a in ACTIONS},
            "misses": [f"{i}: expected {e}, got {g}" for i, e, g in self.pairs if e != g],
            "skipped": self.skipped,
        }


def run(cases: list[GateCase]) -> GateReport:
    """Score every case through the production gate, with its production defaults."""
    from app.config import settings

    gate = ResultValidation(DataGate(), AgentResultValidator())
    report = GateReport()
    for case in cases:
        unmet = [k for k, v in case.requires.items() if getattr(settings, k) != v]
        if unmet:
            report.skipped.append(f"{case.id}: needs {unmet}")
            continue
        got = gate.evaluate(case.qr, question="", sql="SELECT 1").action
        report.pairs.append((case.id, case.expect, got))
    return report


def gate_reasons(report: GateReport, baseline_accuracy: float = 100.0) -> list[str]:
    """Why the release gate refuses this report; empty means it passes."""
    reasons: list[str] = []
    block_precision = report.precision("block")
    if block_precision is not None and block_precision < 100.0:
        wrong = [f"{i} ({e})" for i, e, g in report.pairs if g == "block" and e != "block"]
        reasons.append(f"a legitimate result was BLOCKED: {wrong}")
    if report.accuracy < baseline_accuracy:
        reasons.append(f"gate accuracy {report.accuracy:.1f} < baseline {baseline_accuracy}")
    return reasons
