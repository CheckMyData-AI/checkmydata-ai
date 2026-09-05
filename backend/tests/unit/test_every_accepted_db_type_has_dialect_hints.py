"""The demo path ran with no dialect guidance at all (row 2.12).

`DIALECT_HINTS` is keyed on `clickhouse`, `mongodb`, `mysql`, `postgres`. The
adapter registry accepts eight names: those four plus `mongo`, `postgresql`,
`sqlite` and `mcp`. The lookup is `DIALECT_HINTS.get(db_type, "- Standard SQL
dialect")`, so three accepted names fall through silently.

`sqlite` is the one that matters most, and not because SQLite is common: it is
what `demo.py:101` creates. Every first-touch demo — the funnel that decides
whether a prospect believes the product — ran without dialect guidance, so the
model reached for `NOW()`, `ILIKE` and `::` casts that SQLite does not have.

**The fix is the class, not the symptom.** Adding a `sqlite` key would leave
`postgresql` and `mongo` — names the registry accepts — still falling through.
So the lookup canonicalises the name first, through the registry, which is what
defines the vocabulary in the first place. A ninth accepted name then either has
hints or fails this test.

`mcp` is deliberately excluded: it is a transport, not a SQL dialect, and the
generic fallback is the honest answer for it.
"""

from __future__ import annotations

import pytest

from app.agents.prompts.sql_prompt import DIALECT_HINTS
from app.connectors.registry import ADAPTER_REGISTRY, canonical_dialect

#: Accepted names that are engines rather than transports.
_SQL_ENGINES = sorted(set(ADAPTER_REGISTRY) - {"mcp"})


class TestEveryAcceptedNameResolvesToHints:
    @pytest.mark.parametrize("db_type", _SQL_ENGINES)
    def test_an_accepted_db_type_has_dialect_hints(self, db_type):
        assert DIALECT_HINTS.get(canonical_dialect(db_type)), (
            f"{db_type!r} is accepted by the adapter registry but resolves to no dialect "
            "hints, so the agent writes SQL for an engine nobody described to it"
        )

    def test_the_transport_is_not_expected_to_have_any(self):
        """`mcp` is not a dialect. The generic fallback is the honest answer."""
        assert canonical_dialect("mcp") not in DIALECT_HINTS


class TestTheAliasesResolve:
    @pytest.mark.parametrize(
        ("alias", "canonical"),
        [("postgresql", "postgres"), ("mongo", "mongodb"), ("POSTGRES", "postgres")],
    )
    def test_an_alias_reaches_the_same_hints(self, alias, canonical):
        assert canonical_dialect(alias) == canonical

    def test_an_unknown_name_is_returned_unchanged(self):
        """Canonicalising is not guessing: a name nobody registered stays itself
        and falls through to the generic fallback, which is what it deserves."""
        assert canonical_dialect("duckdb") == "duckdb"


class TestSqliteHintsSayWhatSqliteActuallyLacks:
    """A key with generic content would pass the test above and still let the
    model write `NOW()`. The hints have to name the real differences."""

    def test_it_names_the_datetime_form(self):
        hints = DIALECT_HINTS[canonical_dialect("sqlite")]
        assert "datetime(" in hints.lower() or "strftime" in hints.lower()

    def test_it_warns_off_the_functions_sqlite_does_not_have(self):
        hints = DIALECT_HINTS[canonical_dialect("sqlite")].lower()
        assert "now()" in hints or "ilike" in hints
