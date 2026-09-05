"""The context block named nothing it showed (board row 2.1).

`render_context_block` emitted `a.summary` and never `a.title`. The titles it
dropped are the identifying half of every artifact:

    table         -> the table name
    lineage_edge  -> "entity -> table", the code<->DB link
    rule          -> the rule's name
    rag_chunk     -> the source path
    learning      -> "[category] subject"
    insight       -> the insight's title

So the model was handed descriptions of tables without their names, rules
without their names, and retrieved code without its file — and then asked which
table holds what. This is the default path: `context_planner_enabled` is on.

**The budget already paid for them.** `_size` counts
``f"{artifact.title}\\n{artifact.summary}"`` with the comment "the fields exposed
to the LLM". It believes the title is rendered. So the pack was charged for text
it never sent and fitted fewer artifacts than it could — which is why the fix is
to render the title rather than to stop counting it. Fourth occurrence this
session of one part of the system implementing a contract another does not
honour (cf. 1.7's seal, 1.9's degradation line, 2.9's gate).

**Dedup on `summary` alone is the sharper half.** A table artifact's summary is
`row.business_description or ""` — LLM-generated, and absent on any table that
has not been described. Every such artifact hashes to `""`, so the FIRST one is
kept and all the rest are dropped: a project whose tables lack descriptions gets
a single blank line where its table list should be.

RET-R15's intent — collapse a symbol chunk and a prose chunk describing the same
entity — survives, but **not** for the reason this file first claimed. The first
draft said those two share a title; `test_w2_low_batch::test_ret_r15_dedup_identical_summaries`
proves they do not ("Foo" and "Foo prose", one summary), and it went red. The
distinction is the artifact KIND: `code_entity` and `rag_chunk` are two views of
one entity and still collapse on the summary alone; a `table` or a `rule` is a
distinct entity that may merely share prose, and is keyed on the pair.
"""

from __future__ import annotations

from app.knowledge.context_pack import Artifact
from app.knowledge.context_pack_renderer import render_context_block


def _artifact(title: str, summary: str = "", *, conf: float = 1.0) -> Artifact:
    return Artifact(
        id=f"a:{title}:{summary}",
        type="table",
        title=title,
        summary=summary,
        confidence=conf,
        provenance={"source": "db_index"},
    )


class TestTheTitleReachesThePrompt:
    def test_a_table_name_is_rendered(self):
        block = render_context_block([_artifact("orders", "every purchase")])
        assert "orders" in block

    def test_the_summary_is_still_rendered(self):
        block = render_context_block([_artifact("orders", "every purchase")])
        assert "every purchase" in block

    def test_a_titled_artifact_with_no_summary_still_says_something(self):
        """The common case for tables: `business_description` is generated, and a
        project that has not been described has none."""
        block = render_context_block([_artifact("orders")])
        assert "orders" in block

    def test_an_artifact_with_neither_contributes_no_line(self):
        """A line carrying only provenance tells the reader nothing and spends
        budget doing it."""
        block = render_context_block([_artifact("", "")])
        assert block.count("\n- ") == 0


class TestEmptySummariesNoLongerCollapse:
    def test_three_undescribed_tables_all_survive(self):
        """The sharper half. All three hash to `""` under the old key, so two
        were dropped and the project's table list became one blank line."""
        block = render_context_block(
            [_artifact("orders"), _artifact("users"), _artifact("invoices")]
        )
        for name in ("orders", "users", "invoices"):
            assert name in block, f"{name} was dropped by the summary-only dedup"

    def test_two_tables_sharing_a_description_both_survive(self):
        block = render_context_block(
            [
                _artifact("orders_2024", "archived orders"),
                _artifact("orders_2025", "archived orders"),
            ]
        )
        assert "orders_2024" in block and "orders_2025" in block


class TestRetR15SurvivesTheChange:
    """Its intent was legitimate and its key was too wide.

    Two retrieval VIEWS of one entity — a symbol chunk and the prose chunk about
    it — carry different titles by construction, so a pair key would have stopped
    collapsing them. That is what the existing
    `test_w2_low_batch::test_ret_r15_dedup_identical_summaries` caught, after this
    file asserted the opposite. The kind decides: views collapse on the summary,
    entities on the pair.
    """

    def _view(self, kind: str, title: str, summary: str) -> Artifact:
        return Artifact(
            id=f"{kind}:{title}",
            type=kind,
            title=title,
            summary=summary,
            confidence=0.9,
            provenance={"source": kind},
        )

    def test_two_views_of_one_entity_still_collapse(self):
        block = render_context_block(
            [
                self._view("code_entity", "Foo", "The users table stores user records."),
                self._view("rag_chunk", "Foo prose", "The users table stores user records."),
            ]
        )
        assert block.count("stores user records") == 1

    def test_an_identical_entity_artifact_is_still_collapsed(self):
        dup = _artifact("app/sync.py", "resolves the sync status")
        block = render_context_block([dup, _artifact("app/sync.py", "resolves the sync status")])
        assert block.count("app/sync.py") == 1


class TestTheBudgetWasAlreadyPayingForIt:
    def test_the_sizer_counts_the_title(self):
        """Not a new cost: rendering the title makes the existing accounting
        honest. If this ever stops counting the title, the renderer must stop
        emitting it in the same change — or the pack overflows its budget."""
        import inspect

        from app.knowledge.context_pack_renderer import _make_default_sizer

        assert "title" in inspect.getsource(_make_default_sizer)
