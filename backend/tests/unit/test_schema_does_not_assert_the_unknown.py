"""The schema context asserted nullability nobody had established (row 2.11).

`ColumnInfo.is_nullable` was `bool = True`. Twelve construction sites exist and
four omit it — `mongodb.py:341`, `ssh_exec.py:525`, and two in
`entity_extractor.py` — and every one of those four is a case where nullability
is genuinely **unknown** rather than known-nullable. Mongo has no schema to read
it from; the entity extractor is reading source code.

So the default was an assertion nobody made, in every case that relied on it, and
`schema_context_builder.py:37` printed ` NULL` beside each of those columns as
fact. For a Mongo customer the agent was told every field is nullable.

The type could not say otherwise: a `bool` has no third state. That is the gap
this codebase has already closed three times elsewhere — `reltuples < 0` treated
as unknown (D14), `CallerRef.depth_estimated` replacing a fabricated depth (L12),
`rowcount == -1` kept distinct from `0`.

**Flipping the default is only half of it.** Three of the four readers turn a
falsy value into the OPPOSITE assertion — `"YES" if col.is_nullable else "NO"` —
so `None` would have become "NOT NULL", trading one lie for another. Only
`schema_context_builder` was already right, and by accident: it prints the
positive claim or nothing.

The ClickHouse half of this row is a different shape. `no_pk` fires on every
table of an engine that has no primary keys at all, forever, and this
repository's own doctrine says a warning on the normal path is what teaches
people to ignore warnings. ClickHouse's ordering key is already captured
(`is_sort_key`, W4) and already rendered, so the check keys on that rather than
on the dialect — which says the true thing: this table has what its engine offers
instead of a PK.

**Mongo foreign keys are deliberately NOT added.** MongoDB has none. Inferring
them from ObjectId references is a heuristic, and a schema context that asserts a
relationship the database does not enforce is worse than one that stays quiet —
which is this row's entire subject.
"""

from __future__ import annotations

from app.connectors.base import ColumnInfo


class TestUnknownIsAThirdState:
    def test_the_default_is_unknown_not_nullable(self):
        assert ColumnInfo(name="x", data_type="string").is_nullable is None

    def test_a_connector_that_knows_still_says_so(self):
        assert ColumnInfo(name="x", data_type="text", is_nullable=True).is_nullable is True
        assert ColumnInfo(name="x", data_type="text", is_nullable=False).is_nullable is False


class TestNoReaderTurnsUnknownIntoAnAssertion:
    """`None` is falsy, so every `if col.is_nullable else "NO"` silently claimed
    the opposite. Flipping the default alone would have been a different lie."""

    def test_schema_hints_does_not_claim_not_null(self):
        from app.core.schema_hints import nullability_label

        assert nullability_label(None) == "UNKNOWN"
        assert nullability_label(True) == "YES"
        assert nullability_label(False) == "NO"

    def test_the_prompt_prints_nothing_for_an_unknown_column(self):
        from app.agents.schema_context_builder import nullability_suffix

        assert nullability_suffix(None) == ""
        assert nullability_suffix(True) == " NULL"

    def test_the_validator_does_not_call_it_not_null(self):
        from app.knowledge.db_index_validator import nullability_suffix as validator_suffix

        assert validator_suffix(None) == ""
        assert validator_suffix(False) == " NOT NULL"
        assert validator_suffix(True) == " NULL"


class TestClickHouseStopsBeingToldItHasNoPrimaryKey:
    """An informational issue firing on every table of an engine, forever, is
    noise — and noise on the normal path is what teaches people to ignore the
    signal."""

    def _table(self, *, sort_key: bool):
        from app.connectors.base import TableInfo

        return TableInfo(
            name="events",
            columns=[
                ColumnInfo(name="ts", data_type="DateTime", is_sort_key=sort_key),
                ColumnInfo(name="body", data_type="String"),
            ],
        )

    def _kinds(self, table):
        from app.connectors.base import SchemaInfo
        from app.knowledge.db_index_completeness import check_schema_completeness

        return {i.kind for i in check_schema_completeness(SchemaInfo(tables=[table]))}

    def test_a_table_with_a_sort_key_is_not_reported_as_pk_less(self):
        assert "no_pk" not in self._kinds(self._table(sort_key=True))

    def test_a_table_with_neither_still_is(self):
        """The check keeps working where it means something."""
        assert "no_pk" in self._kinds(self._table(sort_key=False))
