"""The public pages said query results are never stored. Up to 500 rows per message are.

`privacy`, `terms`, `about` and the support FAQ — four surfaces, not the two the audit
named — all carried some form of "query results are transient / never stored on our
servers". Measured against production on 2026-09-02: **55 of 131** chat messages carry a
`raw_result` key and **39** contain a `rows` array, and **213 of 213** `db_index` rows
carry `column_distinct_values_json`, which is sampled live values from the customer's
database.

The product's whole ask is production database credentials, and its binding data-handling
promise was measurably false. Any prospect with a security review fails the product at
diligence — and `vision.md` §8 says the system "never stores data out of a user's
production database", which is the claim the code contradicts.

This test guards the direction that matters: the claim can come back in a sentence long
after the storage it describes has been forgotten. It is a **text** test on purpose —
the defect was never in the code, which does exactly what it says.
"""

from __future__ import annotations

import pathlib

import pytest

_PAGES = pathlib.Path(__file__).parents[4] / "frontend" / "src" / "app" / "(marketing)"

# Phrases that assert results are not kept. Each was on a live page.
_FORBIDDEN = [
    "Query results are transient",
    "query results are transient",
    "never stored on our servers",
    "not persisted on our servers",
    "does not include raw database rows",
    "not include raw database rows",
    "exist only in-memory",
    "exist only in memory",
]


def _surfaces() -> list[pathlib.Path]:
    return sorted(_PAGES.glob("*/page.tsx"))


def test_the_marketing_surfaces_are_where_this_test_thinks_they_are() -> None:
    """A path test that silently matches nothing is worse than no test."""
    names = {p.parent.name for p in _surfaces()}
    assert {"privacy", "terms", "about", "support"} <= names, (
        f"marketing pages moved; this guard is now checking {names or 'nothing'}"
    )


@pytest.mark.parametrize("page", _surfaces(), ids=lambda p: p.parent.name)
def test_no_page_claims_results_are_not_stored(page: pathlib.Path) -> None:
    text = page.read_text(encoding="utf-8")
    found = [phrase for phrase in _FORBIDDEN if phrase in text]
    assert not found, (
        f"{page.parent.name}/page.tsx claims {found!r}. Query results ARE stored: "
        "chat.py puts `raw_result` (capped at chat_raw_result_row_cap = 500 rows) into "
        "the assistant message's metadata, and db_index stores sampled column values. "
        "Either the sentence is wrong or the storage changed — check which before "
        "deleting this test."
    )


def test_the_cap_the_pages_quote_is_the_cap_the_code_uses() -> None:
    """The pages say 500 rows. If the setting moves, the promise silently changes."""
    from app.config import settings

    assert settings.chat_raw_result_row_cap == 500, (
        f"chat_raw_result_row_cap is {settings.chat_raw_result_row_cap}; the privacy "
        "policy, terms and support FAQ all say 500 rows"
    )


@pytest.mark.parametrize("name", ["privacy", "terms", "support"])
def test_the_pages_that_promise_deletion_say_what_deletes_it(name: str) -> None:
    text = (_PAGES / name / "page.tsx").read_text(encoding="utf-8")
    assert "deleted" in text.lower(), f"{name} states what is stored but not what removes it"
