"""PRJ-13 T08a — the routing eval scores, and its gate refuses what it should.

The replay tier IS a CI gate: `test_the_recorded_router_holds_its_baseline` runs the
production parser over the committed recordings and fails the build on a drop of more
than `MAX_DROP_POINTS`. A change to `_parse_route_response`, the capability guards or
`use_complex_pipeline` that re-routes recorded questions shows up here.
"""

from __future__ import annotations

import json

import pytest

from app.eval.routing.harness import (
    BASELINE,
    MAX_DROP_POINTS,
    CaseError,
    Report,
    gate,
    load_cases,
    replay,
    route_from_raw,
    score,
)


def test_the_seed_corpus_is_well_formed_and_covers_three_kinds() -> None:
    cases = load_cases()
    assert len(cases) >= 30
    assert {c.kind for c in cases} == {"happy", "adversarial", "failure"}
    assert all(c.provenance in {"curated", "synthetic", "manual"} for c in cases)


def test_the_recorded_router_holds_its_baseline() -> None:
    report = replay(load_cases())
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert gate(report, baseline) == [], report.to_dict()


def test_a_fallback_is_never_a_correct_route() -> None:
    """The router's default is `explore`, which several cases accept."""
    case = next(c for c in load_cases() if "explore" in c.routes)
    outcome = score(case, route_from_raw(case, ""))
    assert outcome.defaulted and not outcome.route_ok


def test_the_gate_refuses_a_drop_beyond_the_limit_and_an_unscored_case() -> None:
    report = Report()
    case = load_cases()[2]  # R03: query
    for raw in ['{"route": "direct", "complexity": "simple"}'] * 10:
        report.outcomes.append(score(case, route_from_raw(case, raw)))
    assert report.accuracy == 0.0
    assert gate(report, {"accuracy": MAX_DROP_POINTS - 1}) == []
    assert gate(report, {"accuracy": 50.0})
    report.errors.append("R99: no recording")
    assert any("could not be scored" in r for r in gate(report, {"accuracy": 0.0}))


def test_the_interval_is_wilson_and_bounded() -> None:
    report = Report()
    case = load_cases()[2]
    for raw in ['{"route": "query", "complexity": "simple"}'] * 9 + [""]:
        report.outcomes.append(score(case, route_from_raw(case, raw)))
    lo, hi = report.interval()
    assert report.accuracy == 90.0 and 55 < lo < 90 < hi <= 100


def test_a_broken_case_file_is_a_test_error_not_a_verdict(tmp_path) -> None:
    bad = tmp_path / "cases.jsonl"
    row = {
        "id": "X1",
        "question": "q",
        "caps": "db+warp",
        "routes": ["query"],
        "kind": "happy",
        "provenance": "curated",
    }
    bad.write_text(json.dumps(row) + "\n")
    with pytest.raises(CaseError, match="unknown capabilities"):
        load_cases(bad)
