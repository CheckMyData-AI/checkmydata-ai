"""T07c / PRJ-07 S-08 (+S-09) — multi-connection and repo-only projects are served.

* A project with a repository and **no** database connection was never nightly indexed:
  eligibility required a connection, and the orchestrator skipped it as
  `no_active_connections`. Its repository index is real work with a real consumer (the
  codebase answers in chat), so it now runs, and the database steps are honestly absent.
* The index→sync chain after an index started the sync on the FIRST connection and
  stopped; a project with two databases had one map kept fresh.
* The live-table cross-reference introspected the first connection only, with no timeout,
  before the run's heartbeat opened — a hanging tunnel was reaped before the pipeline
  began (S-09).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.daily_knowledge_sync_service import DailyKnowledgeSyncService


def _project(repo=True):
    p = MagicMock()
    p.id = "proj-1"
    p.repo_url = "https://github.com/org/repo.git" if repo else None
    return p


@pytest.mark.asyncio
async def test_a_repo_only_project_is_eligible() -> None:
    svc = DailyKnowledgeSyncService()
    with (
        patch.object(svc, "_project_svc") as projects,
        patch.object(svc, "_active_connections", AsyncMock(return_value=[])),
        patch(
            "app.services.sync_schedule_service.SyncScheduleService.effective",
            AsyncMock(return_value={"enabled": True}),
        ),
    ):
        projects.list_all = AsyncMock(return_value=[_project()])
        assert [p.id for p in await svc.list_eligible_projects(MagicMock())] == ["proj-1"]


@pytest.mark.asyncio
async def test_a_repo_only_project_gets_its_repository_indexed() -> None:
    svc = DailyKnowledgeSyncService()
    repo = AsyncMock(return_value=("completed", None))
    db = AsyncMock()
    with (
        patch.object(svc, "_project_svc") as projects,
        patch.object(svc, "_active_connections", AsyncMock(return_value=[])),
        patch.object(svc, "_run_repo_index", repo),
        patch.object(svc, "_run_db_index", db),
        patch("app.services.daily_knowledge_sync_service.async_session_factory") as sf,
    ):
        projects.get = AsyncMock(return_value=_project())
        sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        sf.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await svc._orchestrate("proj-1")

    repo.assert_awaited_once()
    db.assert_not_awaited()
    assert result.status == "success"
    assert result.steps_json["connections"] == []
    assert result.steps_json.get("reason") == "repo_only"


@pytest.mark.asyncio
async def test_the_chain_starts_a_sync_on_every_connection(monkeypatch) -> None:
    from app.api.routes import repos

    started: list[str] = []

    async def _autostart(connection_id, project_id):
        started.append(connection_id)
        return True

    conns = []
    for i in (1, 2):
        c = MagicMock()
        c.id = f"conn-{i}"
        c.is_active = True
        c.source_type = "database"
        conns.append(c)
    monkeypatch.setattr(repos.settings, "auto_sync_after_index", True)
    monkeypatch.setattr("app.api.routes.connections.maybe_autostart_sync", _autostart)
    monkeypatch.setattr(repos._connection_svc, "list_by_project", AsyncMock(return_value=conns))
    with patch("app.api.routes.repos.async_session_factory") as sf:
        sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        sf.return_value.__aexit__ = AsyncMock(return_value=None)
        await repos._maybe_autostart_sync_chain("proj-1")
    assert started == ["conn-1", "conn-2"]


@pytest.mark.asyncio
async def test_live_tables_come_from_every_database_and_a_hang_is_bounded(monkeypatch) -> None:
    from app.api.routes import repos
    from app.connectors.base import SchemaInfo, TableInfo

    def _conn(cid, kind="database"):
        c = MagicMock()
        c.id, c.is_active, c.source_type = cid, True, kind
        return c

    class _Fast:
        def __init__(self, names):
            self.names = names

        async def connect(self, cfg):
            pass

        async def introspect_schema(self):
            return SchemaInfo(
                tables=[TableInfo(name=n, columns=[]) for n in self.names], db_type="mysql"
            )

        async def disconnect(self):
            pass

    class _Hanging(_Fast):
        async def connect(self, cfg):
            await asyncio.sleep(60)

    connectors = iter([_Fast(["orders"]), _Hanging([]), _Fast(["users"])])
    monkeypatch.setattr(
        repos._connection_svc,
        "list_by_project",
        AsyncMock(return_value=[_conn("a"), _conn("ga", "ga4"), _conn("b"), _conn("c")]),
    )
    monkeypatch.setattr(
        repos._connection_svc,
        "to_config",
        AsyncMock(return_value=MagicMock(db_type="mysql", ssh_exec_mode=False)),
    )
    monkeypatch.setattr("app.connectors.registry.get_connector", lambda *a, **k: next(connectors))
    monkeypatch.setattr(repos, "LIVE_TABLES_TIMEOUT_SECONDS", 0.05)

    names = await repos._fetch_live_table_names(MagicMock(), "proj-1")
    assert sorted(names) == ["orders", "users"], "every database, the hanging one skipped"
