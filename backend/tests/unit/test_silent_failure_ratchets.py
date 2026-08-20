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

**Ratchet 2 — the shape that actually caused an incident.** On 2026-08-09 a `TypeError`
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

#: Broad handlers that return a literal degraded value. 78 at 2026-08-10; 79 at
#: 2026-08-20 — `SQLiteConnector.test_connection` (`app/connectors/sqlite.py:159`),
#: examined rather than waved through. It is the same shape as the other four
#: connectors' `test_connection` (see `mysql.py:369`), all already inside this count:
#: the caller asked "is this alive", `False` is the honest answer to any failure, and
#: it logs at **warning** with the traceback, which is what this ratchet's message asks
#: for. Raising the number is only correct with the instance named — an unexplained
#: bump is how a ratchet becomes a formality.
#: 80 at 2026-08-20 — `_host_key_blob` (`app/connectors/ssh_known_hosts.py`). Examined:
#: a host key that cannot be read must not crash a connection attempt, and `None` is not
#: silent here — the caller logs at warning that the connection is unverified and cannot
#: be pinned, which is the opposite of the failure this ratchet is named after.
MAX_BROAD_DEGRADED_RETURN = 80


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


def test_broad_handlers_returning_a_degraded_value_do_not_grow():
    n = 0
    for tree in _walk():
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
                    n += 1
                    break
    assert n <= MAX_BROAD_DEGRADED_RETURN, (
        f"{n} broad handlers return a literal degraded value, ratchet is "
        f"{MAX_BROAD_DEGRADED_RETURN}. This is the shape that emptied a prompt section "
        "without anyone noticing — if the caller cannot tell your fallback apart from "
        "real emptiness, log at warning, not debug."
    )


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
