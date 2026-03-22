import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import or_ as sqlalchemy_or_

from app.models.dashboard import Dashboard
from app.services.dashboard_service import DashboardService


@pytest.fixture
def session() -> AsyncMock:
    s = AsyncMock()
    s.add = MagicMock()
    s.commit = AsyncMock()
    s.refresh = AsyncMock()
    s.execute = AsyncMock()
    s.delete = AsyncMock()
    return s


@pytest.fixture
def service() -> DashboardService:
    return DashboardService()


class TestCreate:
    async def test_create_creates_and_returns_dashboard(
        self,
        session: AsyncMock,
        service: DashboardService,
    ) -> None:
        kwargs = {
            "project_id": str(uuid.uuid4()),
            "creator_id": str(uuid.uuid4()),
            "title": "Board",
            "layout_json": "{}",
            "cards_json": "[]",
            "is_shared": True,
        }
        result = await service.create(session, **kwargs)
        session.add.assert_called_once()
        added = session.add.call_args[0][0]
        assert isinstance(added, Dashboard)
        assert added.title == "Board"
        assert added.project_id == kwargs["project_id"]
        assert result is added
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(added)


class TestGet:
    async def test_get_found(
        self,
        session: AsyncMock,
        service: DashboardService,
    ) -> None:
        dash = Dashboard(
            project_id=str(uuid.uuid4()),
            creator_id=str(uuid.uuid4()),
            title="T",
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = dash
        session.execute = AsyncMock(return_value=mock_result)
        out = await service.get(session, dash.id)
        assert out is dash
        session.execute.assert_awaited_once()

    async def test_get_not_found(
        self,
        session: AsyncMock,
        service: DashboardService,
    ) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)
        assert await service.get(session, "missing-id") is None


class TestListForProject:
    async def test_list_for_project_returns_rows_and_uses_or_filter(
        self,
        session: AsyncMock,
        service: DashboardService,
    ) -> None:
        d1 = Dashboard(
            project_id=str(uuid.uuid4()),
            creator_id=str(uuid.uuid4()),
            title="A",
        )
        d2 = Dashboard(
            project_id=str(uuid.uuid4()),
            creator_id=str(uuid.uuid4()),
            title="B",
        )
        mock_rows = MagicMock()
        mock_rows.all.return_value = [d1, d2]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_rows
        session.execute = AsyncMock(return_value=mock_result)
        pid = str(uuid.uuid4())
        uid = str(uuid.uuid4())
        with patch(
            "app.services.dashboard_service.or_",
            wraps=sqlalchemy_or_,
        ) as or_mock:
            rows = await service.list_for_project(session, pid, uid)
        or_mock.assert_called_once()
        assert rows == [d1, d2]
        session.execute.assert_awaited_once()
        exec_stmt = session.execute.await_args.args[0]
        assert exec_stmt.whereclause is not None


class TestUpdate:
    async def test_update_allowed_fields(
        self,
        session: AsyncMock,
        service: DashboardService,
    ) -> None:
        dash = Dashboard(
            project_id=str(uuid.uuid4()),
            creator_id=str(uuid.uuid4()),
            title="Old",
            is_shared=False,
            layout_json=None,
            cards_json=None,
        )
        mock_get = MagicMock()
        mock_get.scalar_one_or_none.return_value = dash
        session.execute = AsyncMock(return_value=mock_get)
        out = await service.update(
            session,
            dash.id,
            title="New",
            layout_json="{}",
            cards_json="[]",
            is_shared=True,
        )
        assert out is dash
        assert dash.title == "New"
        assert dash.layout_json == "{}"
        assert dash.cards_json == "[]"
        assert dash.is_shared is True
        session.commit.assert_awaited()
        session.refresh.assert_awaited_once_with(dash)

    async def test_update_ignores_disallowed_fields(
        self,
        session: AsyncMock,
        service: DashboardService,
    ) -> None:
        pid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        dash = Dashboard(
            project_id=pid,
            creator_id=cid,
            title="T",
        )
        other_pid = str(uuid.uuid4())
        other_cid = str(uuid.uuid4())
        mock_get = MagicMock()
        mock_get.scalar_one_or_none.return_value = dash
        session.execute = AsyncMock(return_value=mock_get)
        await service.update(
            session,
            dash.id,
            project_id=other_pid,
            creator_id=other_cid,
            id="should-not-apply",
        )
        assert dash.project_id == pid
        assert dash.creator_id == cid
        assert dash.id != "should-not-apply"

    async def test_update_missing_returns_none(
        self,
        session: AsyncMock,
        service: DashboardService,
    ) -> None:
        mock_get = MagicMock()
        mock_get.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_get)
        assert await service.update(session, "missing", title="x") is None


class TestDelete:
    async def test_delete_success(
        self,
        session: AsyncMock,
        service: DashboardService,
    ) -> None:
        dash = Dashboard(
            project_id=str(uuid.uuid4()),
            creator_id=str(uuid.uuid4()),
            title="T",
        )
        mock_get = MagicMock()
        mock_get.scalar_one_or_none.return_value = dash
        session.execute = AsyncMock(return_value=mock_get)
        assert await service.delete(session, dash.id) is True
        session.delete.assert_awaited_once_with(dash)
        session.commit.assert_awaited_once()

    async def test_delete_not_found(
        self,
        session: AsyncMock,
        service: DashboardService,
    ) -> None:
        mock_get = MagicMock()
        mock_get.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_get)
        assert await service.delete(session, "missing") is False
        session.delete.assert_not_awaited()


class TestAllowedUpdateFields:
    def test_allowed_update_fields(self) -> None:
        assert DashboardService.ALLOWED_UPDATE_FIELDS == {
            "title",
            "layout_json",
            "cards_json",
            "is_shared",
        }
