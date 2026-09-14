"""A tool-call argument may not reach a typed sink without passing a coercion.

The class, in three acts. **One**: a model change on 2026-09-10 started returning
JSON objects where the tool schema declared `type="string"`, and four consecutive
nightly `code_db_sync` runs stored nothing while reporting success. **Two**: the fix
covered that call site and a ladder walk found a sixth field in a module the outage
never touched. **Three**: a later sweep found *five more* in a file the same fix had
already edited — `db_index_validator` got `as_text` on two fields and left the five
siblings in the same constructor raw.

Three passes by a careful reader, three incomplete results. That is the argument for
this test: the class is invisible at the call site, because
`args.get("business_description", "")` reads exactly like a string.

**What counts as a typed sink** — anything that assumes the declared type:
`.strip()` and other `str` methods, `int()` / `float()` / slicing, and being passed
to a constructor whose field is a database column. The check below is deliberately
narrower than that: it flags the *syntactic* shapes that have actually bitten, and
an allowlist carries the reason for every exemption. A guard that flags everything
gets disabled; one that flags what has drawn blood gets kept.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parents[3] / "app"

#: The coercions. A value that has been through one of these is safe by construction.
COERCIONS = {"as_text", "as_int", "as_float", "as_bool"}

#: Methods and builtins that assume the declared type and raise when it is wrong.
TYPE_ASSUMING = {"strip", "lower", "upper", "split", "startswith", "endswith", "format"}
TYPE_ASSUMING_CALLS = {"int", "float", "len"}

#: Exemptions, each with the reason it is safe. A bare name is not enough.
ALLOWED: dict[str, str] = {
    # `_clamp_sync_status` / `_clamp_code_match` / `_coerce_confidence` are
    # themselves coercions — they map any input onto a closed vocabulary.
    "_clamp_sync_status": "maps any value onto a closed set of statuses",
    "_clamp_code_match": "maps any value onto a closed set of match states",
    "_coerce_confidence": "rounds and clamps, and accepts anything",
    "json.dumps": "serialises any type by definition",
    "str": "the coercion itself, spelled inline",
    "bool": "accepts any type",
    "_clamp_confidence": "clamps any numeric-ish input",
}


def _is_coerced(node: ast.AST) -> bool:
    """True when this expression is already a coercion call.

    `as_text(args.get("x")).strip()` is safe: the receiver of `.strip()` is a `str`
    by construction. A guard that cannot see that flags every correct fix as a
    defect — and a guard that cries wolf is one somebody disables.
    """
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if isinstance(f, ast.Name):
        # `str(x)` is the coercion spelled inline and is exactly as safe.
        return f.id in COERCIONS or f.id in ALLOWED
    if isinstance(f, ast.Attribute):
        return f.attr in ALLOWED or f.attr in COERCIONS
    return False


def _arg_reads(tree: ast.AST) -> list[ast.Call]:
    """Every `<something>.get(...)` on tool-call arguments, NOT already coerced."""
    if _is_coerced(tree):
        return []
    out: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr == "get"):
            continue
        base = f.value
        name = getattr(base, "id", None) or getattr(base, "attr", None)
        if name in {"args", "arguments"}:
            out.append(node)
    return out


def _guarded_lines(tree: ast.AST) -> set[int]:
    """Line numbers inside a `try` that catches the error a wrong type would raise.

    `int(args.get("max_results", 5))` wrapped in `except (ValueError, TypeError)` is
    the correct pattern, not a defect: the coercion is the handler. Flagging it
    would teach a reader that this guard does not know what it is looking at.
    """
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        names: set[str] = set()
        for h in node.handlers:
            t = h.type
            if isinstance(t, ast.Name):
                names.add(t.id)
            elif isinstance(t, ast.Tuple):
                names |= {e.id for e in t.elts if isinstance(e, ast.Name)}
        if not names & {"TypeError", "ValueError", "AttributeError", "Exception"}:
            continue
        for stmt in node.body:
            for inner in ast.walk(stmt):
                if hasattr(inner, "lineno"):
                    guarded.add(inner.lineno)
    return guarded


def _python_files() -> list[pathlib.Path]:
    return sorted(APP.rglob("*.py"))


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: str(p.name))
def test_no_tool_argument_is_type_assumed_without_a_coercion(path: pathlib.Path):
    tree = ast.parse(path.read_text())
    guarded = _guarded_lines(tree)
    offenders: list[str] = []

    for node in ast.walk(tree):
        # `args.get("x", "").strip()` — a method that assumes a str
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in TYPE_ASSUMING and _arg_reads(node.func.value):
                if node.lineno not in guarded:
                    offenders.append(
                        f"{path.name}:{node.lineno} .{node.func.attr}() on a raw argument"
                    )
        # `int(args.get("x", 3))` — a builtin that assumes a number
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in TYPE_ASSUMING_CALLS:
                for a in node.args:
                    if _arg_reads(a) and node.lineno not in guarded:
                        offenders.append(
                            f"{path.name}:{node.lineno} {node.func.id}() on a raw argument"
                        )
        # `args.get("x", "")[:255]` — a slice that assumes a sequence
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            if _arg_reads(node.value) and node.lineno not in guarded:
                offenders.append(f"{path.name}:{node.lineno} slicing a raw argument")

    assert not offenders, (
        "a tool-call argument is used as if its declared type were guaranteed:\n  "
        + "\n  ".join(offenders)
        + "\n\nA model may return an object where the schema says `string`; one did, and "
        "four nightly runs stored nothing. Pass it through as_text / as_int / as_float / "
        "as_bool (app/llm/tool_args.py) first."
    )


def test_the_allowlist_carries_a_reason_for_every_entry():
    """An exemption without a reason is how a guard becomes a formality."""
    for name, reason in ALLOWED.items():
        assert reason and len(reason) > 10, f"{name} is exempt with no reason given"


def test_the_coercions_exist_and_are_importable():
    from app.llm import tool_args

    for name in COERCIONS:
        assert hasattr(tool_args, name), f"{name} is named by this guard and does not exist"
