"""F-SQL-02 — the label said "Total rows" and the number was rows *returned*.

`QueryResult.row_count` is set by every connector to `len(data)` after the row cap and the
byte cap have been applied. It means **rows returned**. The formatter the model reads said:

    f"Total rows: {results.row_count}, Execution time: …"

So a query matching fifty thousand rows against a thousand-row cap produced the line
"Total rows: 1000". When truncation is *detected* a banner above it says "capped at 1000
rows (the database has more)" — and the result is a prompt that contradicts itself, where
the mislabelled line is the one that reads like a fact.

The two consumers already disagreed, which is the tell: `answer_validator.py:94` writes
"rows returned", the formatter wrote "Total rows". One of them was wrong and it was not the
validator.

This is `vision.md` §7 — every answer traceable, degradation honest — not a wording
preference. An agent that believes it has the total will state a total, and the user has no
way to see that it counted a page.
"""

from __future__ import annotations

from pathlib import Path

from app.agents.result_handler import format_query_results
from app.connectors.base import QueryResult


def _result(*, rows: int, truncated: bool = False) -> QueryResult:
    return QueryResult(
        columns=["id"],
        rows=[[i] for i in range(rows)],
        row_count=rows,
        execution_time_ms=1.0,
        truncated=truncated,
    )


class TestTheLabelMatchesTheNumber:
    def test_it_does_not_claim_a_total(self):
        out = format_query_results(_result(rows=5))

        assert "Total rows" not in out, (
            "row_count is rows returned; calling it a total invites the agent to state a "
            "total it was never given"
        )

    def test_it_says_returned(self):
        out = format_query_results(_result(rows=5))

        assert "returned" in out.lower()
        assert "5" in out

    def test_the_number_is_still_there(self):
        """The fix is the label, not the data. Removing the count would trade a wrong
        answer for no answer."""
        out = format_query_results(_result(rows=42))

        assert "42" in out


class TestTruncationDoesNotContradictItself:
    def test_the_count_line_says_the_result_is_partial(self):
        """A banner alone left "Total rows: N" sitting underneath it. Two statements about
        the same number, one of them false, and the false one shaped like a fact."""
        out = format_query_results(_result(rows=1000, truncated=True))

        # Selected by prefix, not by "contains 1000 and row": the truncation banner
        # matches that description too, and picking it made the assertion below fail
        # against correct code. A loose selector turns a real check into a coin flip.
        count_line = next(line for line in out.splitlines() if line.startswith("Rows returned:"))
        assert "Total rows" not in count_line
        # Measured: asserting only the absence of the wrong label left the plant that
        # removes the marker green. The line has to say the number is partial, not merely
        # avoid saying it is total — a reader who sees a bare count reads it as complete.
        assert "partial" in count_line.lower()

    def test_the_banner_is_still_there(self):
        out = format_query_results(_result(rows=1000, truncated=True))

        assert "TRUNCATED" in out
        assert "the database has more" in out

    def test_an_untruncated_result_carries_no_truncation_language(self):
        """The other direction matters too: warning about truncation that did not happen
        teaches the agent to discount the warning."""
        out = format_query_results(_result(rows=5))

        assert "TRUNCATED" not in out
        assert "capped" not in out.lower()


class TestTheOtherConsumerAgrees:
    def test_answer_validator_and_the_formatter_use_the_same_word(self):
        """They disagreed, and the disagreement is what located the bug. Asserting they
        match keeps the next edit from re-opening it on the other side."""
        import inspect

        from app.agents import answer_validator

        src = inspect.getsource(answer_validator)

        assert "rows returned" in src
        assert "total rows" not in src.lower()


class TestEmptyAndErrorPathsAreUnchanged:
    def test_no_rows_still_says_so_plainly(self):
        out = format_query_results(QueryResult(columns=["id"], rows=[], row_count=0))

        assert "no rows" in out.lower()

    def test_the_more_rows_hint_counts_what_was_withheld(self):
        """`... and N more rows` is about the formatter's own display cap, not the
        database's — a third meaning for the same number, and it has to stay distinct."""
        out = format_query_results(_result(rows=50))

        assert "30 more rows" in out


class TestNoProducerClaimsATotal:
    """Two producers wrote the same claim, and fixing the one I found and asserting
    completeness is the mistake this session has already made three times — three of six
    heavy `enqueue` sites, two of five rules callers, and now one of two result summaries.

    `viz_agent._summarize_results` had it too, and it matters more than it looks there: that
    summary is what the chart layer reasons over, so a caption carrying a total it does not
    have is a wrong number in a picture, which nobody re-checks.
    """

    def test_no_source_file_labels_row_count_as_a_total(self):
        import ast

        app = Path(__file__).resolve().parents[2] / "app"
        offenders: list[str] = []
        for f in sorted(app.rglob("*.py")):
            src = f.read_text(encoding="utf-8")
            if "row_count" not in src:
                continue
            tree = ast.parse(src)
            for node in ast.walk(tree):
                # An f-string whose literal text says "Total rows" next to a row_count
                # interpolation. Checked on the AST so the comments explaining this fix do
                # not match — a regex flagged exactly that, twice, earlier today.
                if not isinstance(node, ast.JoinedStr):
                    continue
                literal = "".join(
                    v.value for v in node.values if isinstance(v, ast.Constant)
                ).lower()
                interpolated = any(
                    isinstance(v, ast.FormattedValue) and "row_count" in ast.unparse(v.value)
                    for v in node.values
                )
                if "total row" in literal and interpolated:
                    offenders.append(f"{f.name}:{node.lineno}")

        assert not offenders, (
            "these label rows-returned as a total: "
            f"{offenders} — an agent told it has the total will state one"
        )

    def test_the_viz_summary_says_returned(self):
        from app.agents.viz_agent import VizAgent

        out = VizAgent._summarize_results(_result(rows=3))

        assert "Rows returned: 3" in out
        assert "Total rows" not in out

    def test_the_viz_summary_marks_a_truncated_result(self):
        from app.agents.viz_agent import VizAgent

        out = VizAgent._summarize_results(_result(rows=1000, truncated=True))

        assert "partial" in out.lower()
