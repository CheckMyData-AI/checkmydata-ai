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
    declared = len(
        re.findall(r"^\s+\w+\s*:\s*bool\s*=", drift.CONFIG_PY.read_text(encoding="utf-8"), re.M)
    )
    parsed = drift.code_defaults()
    assert len(parsed) == declared, (
        f"config.py declares {declared} bool settings, the checker sees {len(parsed)}"
    )
    # Three whose default is load-bearing enough to be worth pinning by name.
    assert parsed["CROSS_CONNECTION_LEARNINGS_ENABLED"] is False
    assert parsed["RERANKER_ENABLED"] is False
    assert parsed["CODE_GRAPH_ENABLED"] is True, "declared with a trailing comment"


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
    assert drift.code_defaults()["AUTO_SYNC_AFTER_INDEX"] is True, (
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
