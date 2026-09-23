"""PRJ-13 T08b — the result gates, scored against their own contract.

CI gate: `ResultValidation` must never block a result the corpus labels legitimate
(block precision 100%), and total accuracy may not fall below the baseline (100% on the
20 curated cases, 2026-09-23). A planted substring-matching defect — `discount` read as a
`count` — blocks three legitimate results and is refused (measured when this was written).
"""

from __future__ import annotations

import json

import pytest

from app.eval.gates.harness import CaseError, GateReport, gate_reasons, load_cases, run

BASELINE_ACCURACY = 100.0


def test_the_gates_hold_their_contract() -> None:
    report = run(load_cases())
    assert not report.skipped, report.skipped
    assert gate_reasons(report, BASELINE_ACCURACY) == [], report.to_dict()


def test_the_corpus_exercises_every_action() -> None:
    assert {c.expect for c in load_cases()} == {"accept", "warn", "requery", "block"}


def test_a_false_block_fails_the_gate_even_when_accuracy_is_high() -> None:
    report = GateReport(pairs=[(f"C{i}", "accept", "accept") for i in range(99)])
    report.pairs.append(("C99", "accept", "block"))
    assert any("BLOCKED" in r for r in gate_reasons(report, baseline_accuracy=90.0))


def test_an_unknown_action_is_a_test_error(tmp_path) -> None:
    bad = tmp_path / "c.jsonl"
    row = {"id": "X", "columns": [], "rows": [], "expect": "maybe", "note": "n"}
    bad.write_text(json.dumps(row) + "\n")
    with pytest.raises(CaseError, match="unknown action"):
        load_cases(bad)
