"""Per-request state must not live on an object that outlives the request.

This project has hit that bug three times, all in one week and all the same shape:

* `SQLAgent._wall_clock_remaining` — one agent instance serves every request, so
  concurrent callers overwrote each other's query budget (K10);
* `MCPSourceAgent._adapter` — `run()` stashed the caller's adapter on `self` and
  awaited, so one tenant's question reached another tenant's MCP server, and the
  `finally` restore nulled a live request's adapter out from under it (AUD-6);
* `MCPSourceAgent.set_adapter` — a public setter with no callers left after that fix,
  writing the same field. Dead code, and an invitation to reintroduce the bug.

The first was found by accident when an unrelated change had to cross that boundary.
The second by a sweep the first one motivated. This check exists so the third kind is
found by a machine instead.

**Why the reachability walk matters.** A naive sweep looks for classes instantiated at
module level — and would miss every one of the cases above, because `SQLAgent` and
`MCPSourceAgent` are not built at module level. They are built inside
`OrchestratorAgent.__init__`, which is built inside `ConversationalAgent.__init__`,
which *is* module-level (`chat.py`). Lifetime is inherited through construction, so the
walk has to follow it.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"

#: Writes to `self` outside `__init__` on a long-lived class, at 2026-08-12.
#: Set from what THIS test measures, not from a side script. The first attempt used 13,
#: taken from an ad-hoc sweep that counted raw lines while the test counts distinct
#: (file, method, attribute) triples — three of slack, which silently absorbed a
#: deliberately reintroduced bug during the probe. A ratchet with slack is not a
#: ratchet.
#: Every one of the survivors below was read and is lifecycle or cache, not
#: per-request state:
#:   Settings._fix_database_url  — a pydantic validator, runs at construction
#:   SharedCache.connect/close   — the redis handle's lifecycle
#:   WorkflowTracker.*           — subscriber registry and process-wide toggles
#:   LLMRouter.start_health_checks — owns the background task handle
#:   *._get_hybrid_retriever     — caches a PROJECT-AGNOSTIC retriever (the project id
#:                                 is a query argument, not baked into the object)
MAX_SELF_WRITES = 10


def _parse_all() -> dict[str, ast.Module]:
    out: dict[str, ast.Module] = {}
    for f in APP.rglob("*.py"):
        try:
            out[str(f)] = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — a syntax error fails loudly elsewhere
            continue
    return out


def _long_lived(trees: dict[str, ast.Module]) -> set[str]:
    """Classes reachable from a module-level instance, through constructors."""
    roots: set[str] = set()
    for tree in trees.values():
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                name = getattr(node.value.func, "id", None) or getattr(
                    node.value.func, "attr", None
                )
                if name and name[0].isupper():
                    roots.add(name)

    builds: dict[str, set[str]] = {}
    for tree in trees.values():
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            made: set[str] = set()
            for m in cls.body:
                if isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef) and m.name == "__init__":
                    for node in ast.walk(m):
                        if isinstance(node, ast.Call):
                            name = getattr(node.func, "id", None) or getattr(
                                node.func, "attr", None
                            )
                            if name and name[0].isupper():
                                made.add(name)
            builds[cls.name] = made

    live: set[str] = set()
    stack = list(roots)
    while stack:
        c = stack.pop()
        if c in live:
            continue
        live.add(c)
        stack.extend(builds.get(c, ()))
    return live


def test_writes_to_self_on_long_lived_classes_do_not_grow():
    trees = _parse_all()
    live = _long_lived(trees)

    found: set[tuple[str, str, str]] = set()
    for path, tree in trees.items():
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            if cls.name not in live:
                continue
            for m in cls.body:
                if not isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                if m.name == "__init__":
                    continue
                for node in ast.walk(m):
                    if not isinstance(node, ast.Assign):
                        continue
                    for tg in node.targets:
                        if (
                            isinstance(tg, ast.Attribute)
                            and isinstance(tg.value, ast.Name)
                            and tg.value.id == "self"
                        ):
                            found.add((Path(path).name, f"{cls.name}.{m.name}", tg.attr))

    assert len(found) <= MAX_SELF_WRITES, (
        f"{len(found)} writes to `self` outside __init__ on classes that outlive a "
        f"request; ratchet is {MAX_SELF_WRITES}. New ones: {sorted(found)}. "
        "If this is per-request state, put it in the call frame or the run_state dict "
        "— one instance serves every concurrent request in the process."
    )
