"""AUD-0819-05: a backup that skipped the database does not report success.

Production, 2026-08-19T00:00:00Z:

    INFO app.core.backup_manager: Skipping pg_dump on Heroku — use `heroku pg:backups` …
    INFO app.core.backup_manager: Backup complete: reason=scheduled, size=188416 bytes, path=…

The manifest recorded ``{"skipped": true}`` for the database honestly, but the
line an operator reads said "complete", and both callers persisted
``BackupRecord(status="success")`` unconditionally. `vision.md` §7 forbids
telling the user something succeeded when it did not — and this is the one class
of lie that is only discovered when a restore is attempted.

The manifest therefore carries a top-level verdict, in the vocabulary the
analytics collector already established (``ok`` / ``partial`` / ``failed``).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.backup_manager import BackupManager


@pytest.fixture
def mgr(tmp_path: Path) -> BackupManager:
    with patch("app.core.backup_manager.settings") as s:
        s.backup_dir = str(tmp_path / "backups")
        s.backup_retention_days = 7
        s.database_url = "postgresql+asyncpg://u:p@h/db"
        s.chroma_persist_dir = str(tmp_path / "nope-chroma")
        s.custom_rules_dir = str(tmp_path / "nope-rules")
        yield BackupManager()


async def test_heroku_skip_reports_partial_not_complete(mgr: BackupManager, monkeypatch):
    """On Heroku the DB dump is delegated, so the run is partial, never complete."""
    monkeypatch.setenv("DYNO", "web.1")
    manifest = await mgr.run_backup("scheduled")

    assert manifest["files"]["database"]["skipped"] is True
    assert manifest["status"] == "partial", (
        "a run that skipped the database must not read as a completed backup"
    )
    assert "database" in manifest["skipped"]
    assert manifest["database_captured"] is False


async def test_skipped_components_are_named_for_the_operator(mgr: BackupManager, monkeypatch):
    """Every skipped component is listed, so the verdict can be acted on."""
    monkeypatch.setenv("DYNO", "web.1")
    manifest = await mgr.run_backup("scheduled")
    # chroma and rules dirs do not exist in the fixture, so they skip too.
    assert set(manifest["skipped"]) == {"database", "chroma", "rules"}
    assert manifest["status"] == "partial"


async def test_database_captured_is_the_fact_a_restore_depends_on(tmp_path: Path, monkeypatch):
    """`partial` from a missing chroma dir must not read like a missing DB dump.

    A fresh install has no chroma dir, so `partial` alone would be the permanent
    resting state — a warning that is always on is one an operator scrolls past,
    including the once it matters. `database_captured` is the single fact a
    restore depends on, so it is readable on its own.
    """
    monkeypatch.delenv("DYNO", raising=False)
    db_file = tmp_path / "agent.db"
    db_file.write_bytes(b"sqlite-ish bytes")
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "r.md").write_text("rule")
    with patch("app.core.backup_manager.settings") as s:
        s.backup_dir = str(tmp_path / "backups")
        s.backup_retention_days = 7
        s.database_url = f"sqlite+aiosqlite:///{db_file}"
        s.chroma_persist_dir = str(tmp_path / "nope-chroma")
        s.custom_rules_dir = str(rules)
        manifest = await BackupManager().run_backup("manual")

    assert manifest["files"]["database"].get("skipped") is not True
    assert "database" not in manifest["skipped"]
    # chroma is absent in this fixture, so the run is honestly partial ...
    assert manifest["status"] == "partial"
    assert manifest["skipped"] == ["chroma"]
    # ... but the fact that decides whether a restore is possible is true.
    assert manifest["database_captured"] is True


def test_trigger_response_carries_the_verdict():
    """FastAPI drops keys a response model does not declare — silently.

    The verdict, the skipped list and `database_captured` are the whole point of
    AUD-0819-05; if the model omits them the route goes back to answering "ok"
    with no way to tell a delegated database from a captured one.
    """
    from app.api.routes.backup import BackupTriggerResponse

    payload = BackupTriggerResponse(
        timestamp="20260819_000000",
        size_bytes=188416,
        status="partial",
        skipped=["database"],
        database_captured=False,
    ).model_dump()
    assert payload["status"] == "partial"
    assert payload["skipped"] == ["database"]
    assert payload["database_captured"] is False
