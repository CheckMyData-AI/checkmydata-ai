"""Unit tests for the graph-quality benchmark (W6 T11)."""

from __future__ import annotations

from app.eval.graph_benchmark import run_graph_benchmark


def test_benchmark_passes_on_fixture_repo(tmp_path):
    res = run_graph_benchmark(repo_root=None)  # None => writes its own tmp fixture
    assert res.passed, res.failures
    assert res.symbols >= 7
    assert res.extends >= 1
    assert res.calls >= 1


def test_benchmark_result_reports_failures_when_thresholds_unmet(monkeypatch):
    import app.eval.graph_benchmark as gb

    monkeypatch.setattr(gb, "_MIN_SYMBOLS", 9999)
    res = run_graph_benchmark(repo_root=None)
    assert not res.passed
    assert any("symbols" in f for f in res.failures)
