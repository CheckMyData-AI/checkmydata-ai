"""A table name the code never states must not be invented from noise.

This is the product's core promise for a repository added to a dashboard: the agent goes
to the code and knows how it uses the data. Measured against the one real customer
project in production on 2026-08-26 — `esim-php`, a Laravel repository against a 213-table
MySQL database — the code↔DB link named **39** tables, of which **six** exist:

    real:   catalog_phone_numbers  purchases  unlimit_wallets  sentry_samplers
            coverage_rule_import_exceptions  partner_phone_number_tests

    noise:  the  to  if  an  a  get  one  ever  every  group  its  ends  leaves
            clones  interfaces  cascade  current_timestamp  31  any  ases  whatever
            bs  ls  ns  os  pts  res  rs  ses  sts  us  xts  zes

All three rows the product surfaced as `sync_status='mismatch'` — its headline signal,
"your code says one thing and your database says another" — were noise: tables `any`,
`ases`, `whatever`, columns `e` and `now`.

Two independent mechanisms produce that list, and each needs its own guard.

**`TABLE_REF_SQL`** matches ``FROM|JOIN|INTO|UPDATE|TABLE`` followed by a word. Prose
does that: "update to the latest", "insert into if", "from every". So do SQL keywords
that follow those tokens legitimately — ``UPDATE ... CASCADE``, ``INTO ... VALUES``.

**`_model_name_to_table`** pluralises whatever it is handed. Handed a one- or two-
character token it produces something that *looks* like a table: ``z`` → ``zes``,
``s`` → ``ses``, ``pt`` → ``pts``, ``re`` → ``res``. Every one of the twelve suffix
fragments above is that function applied to a fragment.

The guard is deliberately about *shape*, not about a blocklist of the words that happened
to appear here. A blocklist of 33 strings would pass this file and fail the next
repository.
"""

from __future__ import annotations

import pytest

from app.knowledge.entity_extractor import (
    TABLE_REF_SQL,
    _model_name_to_table,
    is_plausible_table_name,
)

#: Verbatim from `code_db_sync` in production, 2026-08-26.
REAL = [
    "catalog_phone_numbers",
    "purchases",
    "unlimit_wallets",
    "sentry_samplers",
    "coverage_rule_import_exceptions",
    "partner_phone_number_tests",
    "firebase_email",
]

NOISE_FROM_SQL = [
    "the",
    "to",
    "if",
    "an",
    "a",
    "get",
    "one",
    "ever",
    "every",
    "group",
    "its",
    "ends",
    "cascade",
    "current_timestamp",
    "31",
    "any",
    "whatever",
]

NOISE_FROM_PLURALISER = [
    "bs",
    "ls",
    "ns",
    "os",
    "pts",
    "res",
    "rs",
    "ses",
    "sts",
    "us",
    "xts",
    "zes",
]


class TestTheShapeTest:
    @pytest.mark.parametrize("name", REAL)
    def test_a_real_table_name_survives(self, name: str) -> None:
        """The guard is worthless if it also removes the six that were right."""
        assert is_plausible_table_name(name), name

    @pytest.mark.parametrize("name", NOISE_FROM_SQL)
    def test_prose_and_keywords_are_refused(self, name: str) -> None:
        assert not is_plausible_table_name(name), name

    @pytest.mark.parametrize("name", NOISE_FROM_PLURALISER)
    def test_pluralised_fragments_are_refused(self, name: str) -> None:
        assert not is_plausible_table_name(name), name

    def test_it_is_a_shape_rule_and_not_a_list_of_these_words(self) -> None:
        """A blocklist would pass this file and fail the next repository. These are
        words that did not appear in production and must still be refused."""
        for invented in ("os", "xs", "ies", "es", "ns", "select", "where", "values", "7"):
            assert not is_plausible_table_name(invented), invented

    def test_short_but_genuine_names_are_not_collateral(self) -> None:
        """Three characters is the floor, so a real short table still passes. Below it
        the signal-to-noise measured on a real repository is not worth the recall."""
        for genuine in ("log", "job", "tag", "kv_store", "acl"):
            assert is_plausible_table_name(genuine), genuine


class TestThePluraliserRefusesFragments:
    """The fix at the source: a fragment cannot become a model, so it cannot become a
    table. `_model_name_to_table` returning empty is how the caller learns to skip it."""

    @pytest.mark.parametrize("fragment", ["z", "s", "e", "u", "pt", "re", "st", "xt", "bs"])
    def test_a_one_or_two_character_model_yields_nothing(self, fragment: str) -> None:
        assert _model_name_to_table(fragment) == "", fragment

    @pytest.mark.parametrize(
        ("model", "table"),
        [
            ("User", "users"),
            ("UserProfile", "user_profiles"),
            ("Category", "categories"),
            ("Person", "people"),
            ("CatalogPhoneNumber", "catalog_phone_numbers"),
        ],
    )
    def test_a_real_model_still_converts(self, model: str, table: str) -> None:
        """The inference is the feature — Laravel and Rails name most tables implicitly.
        Guarding it must not disable it."""
        assert _model_name_to_table(model) == table


class TestTheSqlPatternStillFindsRealReferences:
    """The guard belongs after the regex, not inside it: the pattern must keep matching
    so a genuine reference in prose-adjacent code is still found."""

    def test_a_real_query_still_yields_its_table(self) -> None:
        sql = "SELECT * FROM catalog_phone_numbers JOIN purchases p ON p.id = c.id"
        found = [t for t in TABLE_REF_SQL.findall(sql) if is_plausible_table_name(t)]
        assert found == ["catalog_phone_numbers", "purchases"]

    def test_prose_that_reads_like_sql_yields_nothing(self) -> None:
        prose = "Update to the latest version, then insert into if needed. From every angle."
        found = [t for t in TABLE_REF_SQL.findall(prose) if is_plausible_table_name(t)]
        assert found == [], found

    def test_a_trailing_keyword_is_not_a_table(self) -> None:
        sql = "UPDATE purchases SET x = 1 ON DELETE CASCADE"
        found = [t for t in TABLE_REF_SQL.findall(sql) if is_plausible_table_name(t)]
        assert found == ["purchases"], found

    def test_an_alias_is_not_a_table(self) -> None:
        """`FROM x e` — the alias follows the table, and a one-letter token reaching the
        table list is how `e` became a column name in production."""
        sql = "SELECT e.name FROM employees e WHERE e.id = 1"
        found = [t for t in TABLE_REF_SQL.findall(sql) if is_plausible_table_name(t)]
        assert found == ["employees"], found


class TestTheGuardAppliesOnTheWayInToo:
    """A guard on production does not clean a store.

    `table_usage` is persisted in `project_cache.knowledge_json` and restored on every
    run. Measured 2026-08-27: a full re-index ran with the production-side guard deployed
    — 9 981 files detected, 8 644 parsed, graph rebuilt — and the cache still held **48**
    implausible names afterwards. They were not produced; they were *loaded*, then
    re-saved. Without a filter on `from_json` the noise outlives any number of clean
    extractions, and clearing it needs a manual purge nobody schedules.
    """

    #: Verbatim from `project_cache.knowledge_json`, 2026-08-27 01:00:16, after the
    #: rebuild. Note the casing and the bare integers: both are shapes the guard already
    #: rejects, which is how it is known these were loaded rather than extracted.
    LOADED_NOISE = [
        "0",
        "1328",
        "2",
        "200",
        "3",
        "31",
        "CASCADE",
        "CURRENT_TIMESTAMP",
        "GET",
        "IF",
        "Our",
        "SI",
        "a",
        "an",
        "and",
        "any",
        "ases",
        "bs",
    ]

    def test_deserialising_drops_them(self) -> None:
        import json

        from app.knowledge.entity_extractor import ProjectKnowledge

        payload = {
            "table_usage": {
                name: {"table_name": name, "readers": [], "writers": [], "orm_refs": []}
                for name in [*self.LOADED_NOISE, *REAL]
            }
        }
        loaded = ProjectKnowledge.from_json(json.dumps(payload))
        assert sorted(loaded.table_usage) == sorted(REAL), sorted(loaded.table_usage)

    def test_the_real_names_survive_the_round_trip(self) -> None:
        """Filtering on load is only safe if it is the same rule as on write."""
        import json

        from app.knowledge.entity_extractor import ProjectKnowledge

        payload = {
            "table_usage": {
                n: {"table_name": n, "readers": ["a.php"], "writers": [], "orm_refs": []}
                for n in REAL
            }
        }
        loaded = ProjectKnowledge.from_json(json.dumps(payload))
        again = ProjectKnowledge.from_json(loaded.to_json())
        assert sorted(again.table_usage) == sorted(REAL)
        assert again.table_usage[REAL[0]].readers == ["a.php"], "payload must survive"
