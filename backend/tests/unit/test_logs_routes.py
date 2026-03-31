"""Unit tests for /api/logs/ routes — auth enforcement and response shape."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _mock_user(user_id: str = "test-user-id") -> dict:
    return {"user_id": user_id, "email": "owner@test.com"}


def _mock_db():
    return AsyncMock()


def _fake_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "root_path": "",
        "app": MagicMock(),
    }
    return Request(scope)


class TestLogsRoutesAuth:
    """All /api/logs/ endpoints must enforce owner role."""

    @pytest.mark.asyncio
    async def test_users_requires_owner(self):
        from app.api.routes.logs import _membership_svc, get_log_users

        mock_db = _mock_db()
        mock_user = _mock_user()

        _membership_svc.require_role = AsyncMock(
            side_effect=HTTPException(
                status_code=403,
                detail="Requires at least 'owner' role",
            )
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_log_users(
                request=_fake_request(),
                project_id="proj-1",
                days=30,
                db=mock_db,
                user=mock_user,
            )
        assert exc_info.value.status_code == 403
        _membership_svc.require_role.assert_called_once_with(
            mock_db, "proj-1", "test-user-id", "owner"
        )

    @pytest.mark.asyncio
    async def test_requests_requires_owner(self):
        from app.api.routes.logs import _membership_svc, list_log_requests

        mock_db = _mock_db()
        mock_user = _mock_user()

        _membership_svc.require_role = AsyncMock(
            side_effect=HTTPException(status_code=403, detail="Not owner")
        )

        with pytest.raises(HTTPException) as exc_info:
            await list_log_requests(
                request=_fake_request(),
                project_id="proj-1",
                user_id=None,
                status=None,
                date_from=None,
                date_to=None,
                page=1,
                page_size=50,
                db=mock_db,
                user=mock_user,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_trace_detail_requires_owner(self):
        from app.api.routes.logs import _membership_svc, get_trace_detail

        mock_db = _mock_db()
        mock_user = _mock_user()

        _membership_svc.require_role = AsyncMock(
            side_effect=HTTPException(status_code=403, detail="Not owner")
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_trace_detail(
                request=_fake_request(),
                project_id="proj-1",
                trace_id="trace-1",
                db=mock_db,
                user=mock_user,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_summary_requires_owner(self):
        from app.api.routes.logs import _membership_svc, get_logs_summary

        mock_db = _mock_db()
        mock_user = _mock_user()

        _membership_svc.require_role = AsyncMock(
            side_effect=HTTPException(status_code=403, detail="Not owner")
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_logs_summary(
                request=_fake_request(),
                project_id="proj-1",
                days=7,
                db=mock_db,
                user=mock_user,
            )
        assert exc_info.value.status_code == 403


class TestTraceDetailNotFound:
    @pytest.mark.asyncio
    async def test_returns_404(self):
        from app.api.routes.logs import _logs_svc, _membership_svc, get_trace_detail

        mock_db = _mock_db()
        mock_user = _mock_user()

        _membership_svc.require_role = AsyncMock(return_value="owner")
        _logs_svc.get_trace_detail = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_trace_detail(
                request=_fake_request(),
                project_id="proj-1",
                trace_id="nonexistent",
                db=mock_db,
                user=mock_user,
            )
        assert exc_info.value.status_code == 404
