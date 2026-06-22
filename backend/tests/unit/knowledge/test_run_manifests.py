from __future__ import annotations

import pytest

from app.knowledge.run_manifests import (
    progress_for,
    resolve_manifest,
    step_position,
    total_steps,
)


def test_db_index_manifest_shape():
    m = resolve_manifest("db_index")
    keys = [s.key for s in m]
    assert keys == [
        "introspect_schema",
        "fetch_samples",
        "load_context",
        "validate_tables",
        "store_results",
        "generate_summary",
    ]
    assert total_steps(m) == 6


def test_index_repo_flag_gated_steps_appended():
    base = resolve_manifest("index_repo")
    with_graph = resolve_manifest("index_repo", flags={"code_graph_enabled": True})
    assert "ast_parse" not in [s.key for s in base]
    assert "ast_parse" in [s.key for s in with_graph]
    assert "graph_build" in [s.key for s in with_graph]


def test_progress_math_weighted():
    # db_index weights: 1,1,1,3,1,1 -> total weight 8.
    m = resolve_manifest("db_index")
    assert progress_for(m, 0) == 0
    assert progress_for(m, 3) == round(3 / 8 * 100)  # 38
    assert progress_for(m, 4) == round(6 / 8 * 100)  # 75 (after validate_tables, weight 3)
    assert progress_for(m, 6) == 100


def test_progress_monotonic_non_decreasing():
    m = resolve_manifest("code_db_sync")
    seen = [progress_for(m, i) for i in range(total_steps(m) + 1)]
    assert seen[0] == 0
    assert seen[-1] == 100
    assert all(b >= a for a, b in zip(seen, seen[1:], strict=False))


def test_step_position_is_one_based():
    m = resolve_manifest("db_index")
    assert step_position(m, "introspect_schema") == 1
    assert step_position(m, "generate_summary") == 6
    with pytest.raises(KeyError):
        step_position(m, "nope")


def test_unknown_kind_raises():
    with pytest.raises(KeyError):
        resolve_manifest("not_a_kind")
