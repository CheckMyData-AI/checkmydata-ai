"""Sixty-nine per cent of the corpus is history, and the header did not say so.

B-11. Measured on production 2026-09-15 over 782 knowledge documents:

| doc_type | count |
|---|---|
| `migration` | 537 |
| `orm_model` | 232 |
| everything else | 13 |

And within the migrations: **286 `alter`, 13 `drop`, 204 `create`**. Every `alter`
document describes an INTERMEDIATE state of a table — the column widths, defaults and
names as they were the day it ran. Once a later migration touches the same column, the
earlier document describes a schema that no longer exists, and it sits in retrieval with
exactly the weight of the current one.

The agent's only clue was the file path. The header read
`### api/database/migrations/2022_11_24_160945_create_sendmail_tags_mapping.php` and
nothing said that reading it as the current schema would be wrong.

So the chunk says what kind of claim it is — the same move B-12 made one layer over, where
a counted fact now carries the word MEASURED and a hedged one does not. A marker costs one
line per chunk and turns a document that competes with the truth into one that points at
it.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.agents.knowledge_agent import _CLAIM_KIND, claim_kind_marker

AGENT = pathlib.Path(__file__).resolve().parents[3] / "app" / "agents" / "knowledge_agent.py"


class TestTheMarker:
    def test_a_migration_is_marked_as_history(self) -> None:
        marker = claim_kind_marker("migration")
        assert "HISTORY" in marker
        assert "not the schema as it is now" in marker

    def test_an_orm_model_is_marked_as_what_the_code_declares(self) -> None:
        """The model is not the database: it can omit a column the database has, and
        name one that was dropped."""
        assert "CODE" in claim_kind_marker("orm_model")

    def test_both_markers_name_where_the_truth_is(self) -> None:
        """A qualifier that only casts doubt makes the agent less certain and no better
        informed. Each of these points at the authority instead."""
        for doc_type in _CLAIM_KIND:
            assert "database index is authoritative" in claim_kind_marker(doc_type)

    @pytest.mark.parametrize("doc_type", ["raw_sql", "query_pattern", "project_summary", ""])
    def test_a_document_that_describes_itself_gets_no_marker(self, doc_type: str) -> None:
        """Marking everything is the same as marking nothing: the two types that DO make
        a claim about the database are ignorable the moment every chunk carries a
        qualifier."""
        assert claim_kind_marker(doc_type) == ""

    def test_an_unknown_type_gets_no_marker(self) -> None:
        """A type this table does not know is not evidence of anything, and inventing a
        qualifier for it would be a claim nobody measured."""
        assert claim_kind_marker("something_new") == ""

    def test_the_lookup_is_forgiving_about_shape(self) -> None:
        assert claim_kind_marker(" Migration ") == claim_kind_marker("migration")

    def test_a_missing_type_does_not_raise(self) -> None:
        """`meta.get("doc_type", "")` can hand this `None` from a chunk written before
        the field existed, and a prompt builder that raises takes the answer with it."""
        assert claim_kind_marker(None) == ""  # type: ignore[arg-type]


def test_the_renderer_marks_the_chunk_it_hands_the_agent() -> None:
    """Walked rather than asserted through a mock, because the defect was never in the
    marker — it was that the text handed to the agent did not carry one.

    The first version of this walk looked for `claim_kind_marker` ANYWHERE within a few
    lines of the header, and a planted defect sailed past it: the call was still there,
    two lines up, feeding a variable the chunk no longer used. A guard that checks
    proximity checks nothing. This one follows the value — the name appended to `parts`
    is the text the agent reads, so its assignment is what must reference the marker.
    """
    tree = ast.parse(AGENT.read_text(encoding="utf-8"))

    def _enclosing(target: ast.AST) -> ast.AST | None:
        for fn in ast.walk(tree):
            if isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef) and any(
                n is target for n in ast.walk(fn)
            ):
                return fn
        return None

    headers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr) and "###" in ast.unparse(node)
    ]
    assert headers, "no chunk header found — the walker has stopped measuring"

    checked = 0
    for header in headers:
        fn = _enclosing(header)
        if fn is None:
            continue
        # What is appended to `parts` is what reaches the agent.
        appended: set[str] = {
            call.args[0].id
            for call in ast.walk(fn)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "append"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "parts"
            and call.args
            and isinstance(call.args[0], ast.Name)
        }
        if not appended:
            continue
        for stmt in ast.walk(fn):
            if not isinstance(stmt, ast.Assign):
                continue
            names = {t.id for t in stmt.targets if isinstance(t, ast.Name)}
            if not names & appended:
                continue
            checked += 1
            assert "marker" in ast.unparse(stmt.value), (
                f"knowledge_agent.py:{stmt.lineno} builds the text handed to the agent "
                "without saying what kind of claim the document makes"
            )

    assert checked, "no chunk assignment was reached — the walk no longer measures anything"
