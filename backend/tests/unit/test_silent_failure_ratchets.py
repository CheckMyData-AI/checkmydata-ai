"""Ratchets on two ways this codebase can fail without saying so.

Both counts may shrink and must never grow. They are deliberately ratchets rather
than zero-tolerance rules: most of the handlers behind them are correct, and a rule
that forbids a legitimate pattern gets suppressed rather than obeyed.

**Ratchet 1 — silent `except: pass`.** Measured by AST, not grep: the audit said 52,
the parser says 57. The ones on gate paths were checked by hand and are legitimate —
narrow typed parse loops (`data_gate`), and metrics increments that must never break
the verdict they measure (`result_validation`, `required_filter_guard`, the latter
carrying a comment saying exactly that). This ratchet exists to stop new ones
appearing unexamined, not to condemn the existing ones.

**Ratchet 2 — the shape that actually caused an incident**, and it counts only the
*silent* ones. A first version counted every broad handler returning a literal, reached 81,
and was bumped four times in a day for handlers that logged at `error` with a traceback;
measured, 37 of the 81 announced themselves and 44 did not. A ratchet that flags code
complying with its own message can only grow. On 2026-08-09 a `TypeError`
in a prompt helper was caught by a broad `except`, logged at **debug** (invisible at
production log level) and turned into `""`. The agent received a prompt whose critical
warnings block was empty, and nothing anywhere said so: a crash and "there are no
warnings" produced identical output. `except: pass` was never the dangerous pattern —
*broad except returning a literal degraded value* is, and there are far more of those.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"

#: Handlers whose entire body is `pass`. 57 at 2026-08-10.
MAX_SILENT_PASS = 57

#: Broad handlers that return a literal degraded value **without saying so**. 44 at
#: 2026-08-20.
#:
#: This replaces a count of *all* broad-degrading handlers, which stood at 78 and was
#: bumped four times in one day — 79, 80, 81 — each time for a handler that logged at
#: `error` with a traceback. Measured at the fourth bump: of 81 such handlers, **37 log
#: at warning or above and 44 do not**. The ratchet was flagging code that already did
#: what its own failure message asks for ("log at warning, not debug"), so the number
#: could only ever grow and had stopped measuring anything.
#:
#: The rule is now the incident: on 2026-08-09 a `TypeError` in a prompt helper was caught
#: broadly, logged at **debug**, and turned into `""`. A crash and "there are no warnings"
#: produced identical output. What made that dangerous was the silence, not the breadth —
#: so a handler that degrades *and announces it* is not a violation, and 44 is a debt that
#: can actually be paid down.
#:
#: Lower is better and this must never grow. Adding a broad handler that returns a literal
#: is fine; adding one that does it quietly is not.
MAX_SILENT_BROAD_DEGRADED_RETURN = 44


def _walk() -> list[ast.Module]:
    out = []
    for f in sorted(APP.rglob("*.py")):
        try:
            out.append(ast.parse(f.read_text(encoding="utf-8")))
        except SyntaxError:  # pragma: no cover — a syntax error fails elsewhere, loudly
            continue
    return out


def test_silent_pass_handlers_do_not_grow():
    n = 0
    for tree in _walk():
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                body = [
                    s
                    for s in node.body
                    if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
                ]
                if len(body) == 1 and isinstance(body[0], ast.Pass):
                    n += 1
    assert n <= MAX_SILENT_PASS, (
        f"{n} silent `except: pass` handlers, ratchet is {MAX_SILENT_PASS}. A new one "
        "needs either a log line or a comment saying why silence is correct here."
    )


def test_broad_handlers_that_degrade_quietly_do_not_grow():
    """Count only the handlers that degrade without announcing it.

    A `logger.warning/error/exception/critical` anywhere in the handler counts as
    announcing. That is deliberately generous — it does not check the log line says
    anything useful — because the alternative is judging prose in a test, and the
    measurable half is the one that caused the incident.
    """
    n = 0
    offenders: list[str] = []
    for path, tree in _walk_with_paths():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            broad = node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id == "Exception"
            )
            if not broad:
                continue
            for r in (s for s in ast.walk(node) if isinstance(s, ast.Return)):
                v = r.value
                if isinstance(v, ast.Constant) or (
                    isinstance(v, ast.Tuple) and all(isinstance(e, ast.Constant) for e in v.elts)
                ):
                    if not _announces(node):
                        n += 1
                        offenders.append(f"{path.name}:{node.lineno}")
                    break
    assert n <= MAX_SILENT_BROAD_DEGRADED_RETURN, (
        f"{n} broad handlers return a literal degraded value without logging at warning "
        f"or above, ratchet is {MAX_SILENT_BROAD_DEGRADED_RETURN}. This is the shape that "
        "emptied a prompt section without anyone noticing: if the caller cannot tell your "
        "fallback apart from real emptiness, say so at warning or above. "
        f"Offenders: {sorted(offenders)[:8]}"
    )


def _announces(handler: ast.ExceptHandler) -> bool:
    """True when the handler logs at warning or above somewhere in its body."""
    for n in ast.walk(handler):
        if isinstance(n, ast.Call) and getattr(n.func, "attr", None) in (
            "warning",
            "error",
            "exception",
            "critical",
        ):
            return True
    return False


def _walk_with_paths() -> list[tuple[Path, ast.Module]]:
    out = []
    for f in sorted(APP.rglob("*.py")):
        try:
            out.append((f, ast.parse(f.read_text(encoding="utf-8"))))
        except SyntaxError:  # pragma: no cover
            continue
    return out


def test_prompt_loaders_report_their_failures_at_warning():
    """A prompt section missing because of a crash is not the same event as no data.

    These loaders all degrade to an empty string. At `debug` that degradation is
    invisible in production, so the agent silently answers with its safety notes
    missing. They log at `warning` and say what the consequence is.
    """
    src = (APP / "agents" / "sql_agent.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    offenders: list[str] = []
    for d in ast.walk(tree):
        if not isinstance(d, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        if not d.name.startswith("_load_"):
            continue
        for node in ast.walk(d):
            if isinstance(node, ast.ExceptHandler):
                seg = ast.get_source_segment(src, node) or ""
                if "logger.debug" in seg and "return" in seg:
                    offenders.append(f"{d.name}:{node.lineno}")

    assert not offenders, (
        f"these prompt loaders hide a crash as an empty section at debug level: {offenders}"
    )
