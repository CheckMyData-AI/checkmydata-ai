"""Every SQL string that reaches psycopg must be SQL psycopg will accept.

PRJ-14 / B-03. The narrow version of this check already exists beside it:
`test_pgvector_sql_is_valid.py` drives `PgVectorStore`'s real methods with a stub pool
and compiles what they compose. It was written for a production failure on 2026-09-11 —
a rebuild ran 1 174 s and died with ::

    only '%s', '%b', '%t' are allowed as placeholders, got '%''

because ``" AND doc_id LIKE 'sym:%'"`` was appended by concatenation and psycopg scans
the query TEXT for client-side placeholders before it ever reaches the server. A literal
``%`` must be written ``%%``.

The board asked for the check across `app/`, on the assumption that other modules also
compose psycopg SQL. **Measured: two do.** `PgVectorStore`, which the runtime test
covers, and `models/base.py`, whose `pg_advisory_lock` statement is an f-string —
uncovered until now, safe today only because the value it interpolates is an integer
constant.

So this test is a static reader rather than a second runtime harness. It resolves each
statement as far as the syntax allows — a literal, an f-string's literal parts, a
concatenation — and compiles the result. That reduction is exactly the right one for
this defect class: the placeholder scanner reads the LITERAL text, so a stray ``%`` in a
literal fragment survives every interpolation and is caught here no matter how the pieces
were assembled.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from psycopg._queries import _split_query

APP = pathlib.Path(__file__).resolve().parents[3] / "app"

#: Stands in for an interpolated value. Neutral to the placeholder scanner and to the
#: SQL shape, so what is compiled is the literal text the author actually wrote.
_INTERPOLATED = "1"


def _modules_that_reach_psycopg() -> list[pathlib.Path]:
    out = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                a.name.split(".")[0] in {"psycopg", "psycopg_pool"} for a in node.names
            ):
                out.append(path)
                break
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in {
                "psycopg",
                "psycopg_pool",
            }:
                out.append(path)
                break
    return out


def _resolve(node: ast.expr) -> str | None:
    """The literal text of a statement, with interpolations neutralised."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        parts = []
        for piece in node.values:
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                parts.append(piece.value)
            elif isinstance(piece, ast.FormattedValue):
                parts.append(_INTERPOLATED)
            else:  # pragma: no cover - the grammar has no third member
                return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _resolve(node.left), _resolve(node.right)
        if left is None or right is None:
            return None
        return left + right
    return None


def _statements() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in _modules_that_reach_psycopg():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in {"execute", "executemany"} or not node.args:
                continue
            sql = _resolve(node.args[0])
            if sql is None or not sql.strip():
                continue
            if sql.strip().upper().startswith("PRAGMA"):
                continue  # SQLite's own dialect, on the SQLAlchemy side of this module
            found.append((str(path.relative_to(APP.parent)), node.lineno, sql))
    return found


def test_the_walker_still_finds_the_statements_it_is_meant_to_check() -> None:
    """A guard that has quietly stopped matching passes forever.

    Both known composers must appear, by name: the store the runtime test covers, and
    the migration lock this static reader added.
    """
    files = {f for f, _, _ in _statements()}
    assert any(f.endswith("pgvector_store.py") for f in files), files
    assert any(f.endswith("models/base.py") for f in files), files


@pytest.mark.parametrize(
    ("where", "sql"),
    [((f"{f}:{line}"), sql) for f, line, sql in _statements()],
    ids=lambda v: v if isinstance(v, str) and ":" in v[:40] else "",
)
def test_a_statement_psycopg_will_reject_is_caught_before_production(where: str, sql: str) -> None:
    try:
        _split_query(sql.encode())
    except Exception as exc:  # noqa: BLE001 - the message is the whole point
        pytest.fail(
            f"{where} composes SQL psycopg refuses: {exc}\n\n{sql}\n\n"
            "psycopg scans the query TEXT for client-side placeholders before it reaches "
            "the server, so a literal `%` inside a string literal must be written `%%`."
        )
