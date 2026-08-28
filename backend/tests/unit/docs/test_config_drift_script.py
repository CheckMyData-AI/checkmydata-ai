"""The drift check has to be able to fail, and the recorded list has to stay honest.

`scripts/config_drift.py` is the thing standing between a deliberate deployment choice
and ten undocumented ones. Two ways it could quietly stop working, and both would look
like success:

* **It reports no drift because it parsed nothing.** An empty defaults map or an empty
  config makes every comparison vacuous and the exit code green.
* **The recorded list rots.** A key retired from `config.py` leaves a `DELIBERATE` entry
  that documents a setting nobody reads — and a stale record is trusted the same way a
  fresh one is.

Ten real settings were found diverging on 2026-08-23 (`CLUSTERING_ENABLED`,
`CROSS_CONNECTION_LEARNINGS_ENABLED` and eight others). The fixture below is that exact
set, so the check is exercised against the case it was built for rather than an invented
one.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "scripts" / "config_drift.py"


@pytest.fixture(scope="module")
def drift():
    spec = importlib.util.spec_from_file_location("config_drift", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["config_drift"] = module
    spec.loader.exec_module(module)
    return module


def test_the_script_exists_and_is_executable(drift) -> None:
    assert SCRIPT.exists()
    assert SCRIPT.stat().st_mode & 0o111, "runnable as `./scripts/config_drift.py`"


def test_it_reads_every_bool_setting_config_py_declares(drift) -> None:
    """Counted against the file, not against a number typed here.

    The first version of the pattern anchored on end-of-line and so lost the three
    declarations carrying a trailing comment — `code_graph_enabled`, `lineage_enabled`,
    `auth_cookie_secure`. A setting the checker cannot see is reported as no drift,
    which is the failure mode this whole script exists to remove.
    """
    text = drift.CONFIG_PY.read_text(encoding="utf-8")
    declared = len(re.findall(r"^\s+\w+\s*:\s*bool\s*=", text, re.M))
    parsed = drift.code_defaults()
    seen_bools = {k for k, v in parsed.items() if v in ("true", "false")}
    assert len(seen_bools) == declared, (
        f"config.py declares {declared} bool settings, the checker sees {len(seen_bools)}"
    )
    # Values are normalised to strings since 2026-08-28, when the checker was widened
    # past booleans — one comparison path for bool, str and int. Three whose default is
    # load-bearing enough to be worth pinning by name.
    assert parsed["CROSS_CONNECTION_LEARNINGS_ENABLED"] == "false"
    assert parsed["RERANKER_ENABLED"] == "false"
    assert parsed["CODE_GRAPH_ENABLED"] == "true", "declared with a trailing comment"


def test_every_recorded_divergence_names_a_setting_that_still_exists(drift) -> None:
    """A `DELIBERATE` entry for a setting `config.py` no longer has is a record of
    nothing, read with the same confidence as a live one."""
    defaults = drift.code_defaults()
    orphans = sorted(k for k in drift.DELIBERATE if k not in defaults)
    assert not orphans, (
        f"recorded as deliberate but absent from config.py: {orphans}. Retire the entry "
        "in the same change that retired the setting."
    )


def test_every_recorded_divergence_carries_a_reason(drift) -> None:
    thin = sorted(k for k, why in drift.DELIBERATE.items() if len(why.strip()) < 40)
    assert not thin, f"recorded without a usable reason: {thin}"


def test_the_ten_that_were_found_are_reported_as_drift(drift) -> None:
    """The 2026-08-23 production config, in the shape the check has to catch."""
    found_in_prod = {
        "CLUSTERING_ENABLED": "true",
        "GIT_POLL_ENABLED": "true",
        "GIT_WEBHOOK_ENABLED": "true",
        "AUTO_SYNC_AFTER_INDEX": "true",
        "FRESHNESS_RECONCILER_ENABLED": "true",
        "SCHEMA_CHANGE_ALERTS_ENABLED": "true",
        "ANALYTICS_COLLECT_ENABLED": "true",
        "DATA_GATE_LLM_SEMANTICS": "true",
        "CROSS_CONNECTION_LEARNINGS_ENABLED": "true",
        "RERANKER_ENABLED": "true",
    }
    drifted, recorded, unparseable = drift.compare(found_in_prod, drift.code_defaults())

    # `AUTO_SYNC_AFTER_INDEX` left the set on 2026-08-27, and the reason is the point of
    # keeping this fixture historical rather than editing it: the flag was not drifting,
    # it was mis-grouped. It sat under the ingestion-automation rule ("nothing calls out
    # on a schedule unasked") while the sync it gates calls out to nothing — zero
    # references to `adapter`, `connector`, `execute_query`, `introspect`, `httpx` or
    # `aiohttp` in `code_db_sync_pipeline.py`. Unsetting it made a full re-index leave its
    # own code↔DB map carrying the previous night's timestamp, so the default is now on
    # and `true` in production is agreement, not divergence.
    #
    # The other nine were genuine drift and still are.
    was_misgrouped = {"AUTO_SYNC_AFTER_INDEX"}
    assert sorted(k for k, _, _ in drifted) == sorted(set(found_in_prod) - was_misgrouped)
    assert recorded == []
    assert unparseable == []
    assert drift.code_defaults()["AUTO_SYNC_AFTER_INDEX"] == "true", (
        "if this default goes back to False, the flag is drift again and this test "
        "should be the thing that says so"
    )


def test_a_recorded_divergence_is_not_drift(drift) -> None:
    drifted, recorded, _ = drift.compare({"MCP_ENABLED": "true"}, drift.code_defaults())
    assert drifted == []
    assert [k for k, _, _ in recorded] == ["MCP_ENABLED"]


def test_a_value_matching_the_default_is_neither(drift) -> None:
    drifted, recorded, _ = drift.compare({"RERANKER_ENABLED": "false"}, drift.code_defaults())
    assert (drifted, recorded) == ([], [])


def test_a_boolean_that_is_neither_true_nor_false_is_named(drift) -> None:
    """pydantic will either coerce it or refuse to boot; both are surprises, and a
    check that silently skipped the value would let either happen unannounced."""
    _, _, unparseable = drift.compare({"RERANKER_ENABLED": "maybe"}, drift.code_defaults())
    assert [k for k, _, _ in unparseable] == ["RERANKER_ENABLED"]


def test_settings_absent_from_config_py_are_ignored(drift) -> None:
    """Deployments carry credentials and platform vars that are not settings at all."""
    drifted, recorded, unparseable = drift.compare(
        {"DATABASE_URL": "postgres://…", "PORT": "8000"}, drift.code_defaults()
    )
    assert (drifted, recorded, unparseable) == ([], [], [])


# --------------------------------------------------------------------------------------
# 2026-08-28: the checker was boolean-shaped, and the risk never was.
#
# `VECTOR_STORE_BACKEND` decides whether the entire knowledge layer reads from Postgres
# or from a dyno's local disk. It is a `str`. It was set in production against a code
# default of "chroma", and this script printed "No drift" — because it only ever read
# `name: bool = X`. The tool was written after ten *boolean* divergences were found and
# inherited the shape of its first evidence as an assumption about the whole problem.
#
# Widening it immediately printed `MASTER_ENCRYPTION_KEY`, `OPENROUTER_API_KEY` and the
# Redis password to stdout, which is where CI logs live. Both fixes are asserted here:
# a setting with no code default is not drift (that is how every credential is
# declared), and any value whose NAME looks like a credential is never printed at all.
# --------------------------------------------------------------------------------------


def test_it_reads_string_and_int_settings_too(drift) -> None:
    """The one that would have caught `VECTOR_STORE_BACKEND` the day it was set."""
    defaults = drift.code_defaults()
    assert defaults.get("VECTOR_STORE_BACKEND") == "chroma"
    assert defaults.get("DEFAULT_LLM_PROVIDER") == "openai"
    assert defaults.get("EMBEDDING_UPSERT_BATCH_SIZE") == "8"


def test_booleans_still_compare_case_and_spelling_insensitively(drift) -> None:
    """Widening must not lose what the narrow version did: `1`, `on` and `TRUE` all
    mean the same thing to pydantic and must mean it here."""
    key = "DATA_GATE_HARD_CHECKS_ENABLED"
    assert key not in drift.DELIBERATE, (
        "pick a key with no recorded reason, or this test measures the wrong thing"
    )
    for raw in ("true", "TRUE", "1", "on", "yes"):
        drifted, _, _ = drift.compare({key: raw}, {key: "false"})
        assert drifted, raw


def test_a_setting_with_no_code_default_is_not_drift(drift) -> None:
    """An empty default is not a default — it is "the environment supplies this", which
    is how every credential in config.py is declared. Comparing a deployed secret
    against "" reports all of them AND prints their values."""
    drifted, recorded, unparseable = drift.compare(
        {"OPENROUTER_API_KEY": "sk-or-v1-something"}, {"OPENROUTER_API_KEY": ""}
    )
    assert not drifted and not recorded and not unparseable


def test_environment_shaped_settings_are_not_decisions(drift) -> None:
    """A container path differs from a relative dev path by construction and always
    will. Reporting that as a decision needing a written reason is how a tool teaches
    people to skim it."""
    drifted, _, _ = drift.compare(
        {"REPO_CLONE_BASE_DIR": "/app/data/repos"}, {"REPO_CLONE_BASE_DIR": "./data/repos"}
    )
    assert not drifted
    assert "REPO_CLONE_BASE_DIR" in drift.ENVIRONMENT_SHAPED


def test_a_behaviour_setting_is_still_a_decision(drift) -> None:
    """The other side of that line: which vendor answers a question is a choice, and it
    must still demand a recorded reason."""
    assert "DEFAULT_LLM_PROVIDER" not in drift.ENVIRONMENT_SHAPED
    # It IS recorded in DELIBERATE — so it lands in `recorded`, not `drifted`. What is
    # asserted is that it lands in one of them at all, which a location-shaped setting
    # does not.
    drifted, recorded, _ = drift.compare(
        {"DEFAULT_LLM_PROVIDER": "anthropic"}, {"DEFAULT_LLM_PROVIDER": "openai"}
    )
    assert drifted or recorded


class TestNoValueThatLooksLikeACredentialIsEverPrinted:
    """The check is on the NAME, because the value is exactly what must not be examined
    to make the decision."""

    @pytest.mark.parametrize(
        "key",
        [
            "MASTER_ENCRYPTION_KEY",
            "OPENROUTER_API_KEY",
            "REDIS_URL",
            "JWT_SECRET",
            "SENTRY_DSN",
            "RESEND_API_KEY",
            "STRIPE_SECRET_KEY",
        ],
    )
    def test_it_is_masked(self, drift, key: str) -> None:
        out = drift.mask(key, "hunter2-the-real-value")
        assert "hunter2" not in out
        assert "hidden" in out

    def test_an_ordinary_setting_is_shown(self, drift) -> None:
        """Masking everything would make the report useless — the point is to read it."""
        assert drift.mask("VECTOR_STORE_BACKEND", "pgvector") == "pgvector"
        assert drift.mask("DEFAULT_LLM_PROVIDER", "openrouter") == "openrouter"
