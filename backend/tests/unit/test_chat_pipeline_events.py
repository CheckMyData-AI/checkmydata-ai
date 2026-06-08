"""SSE pipeline event routing contract tests."""

from __future__ import annotations

import ast
from pathlib import Path


def test_chat_pipeline_events_includes_data_gate() -> None:
    chat_path = Path(__file__).resolve().parents[2] / "app" / "api" / "routes" / "chat.py"
    source = chat_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    frozenset_literals: list[set[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "frozenset":
            continue
        if not node.args:
            continue
        arg = node.args[0]
        if not isinstance(arg, ast.Set):
            continue
        names = set()
        for elt in arg.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                names.add(elt.value)
        if "plan" in names and "checkpoint" in names:
            frozenset_literals.append(names)

    assert frozenset_literals, "Expected pipeline_events frozenset in chat.py"
    pipeline_events = frozenset_literals[0]
    assert "data_gate" in pipeline_events
