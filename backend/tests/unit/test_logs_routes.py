"""Unit tests for /api/logs/ routes — auth enforcement and response shape."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app


def _mock_user(user_id: str = "test-user-id") -> dict:
    return {"user_id": user_id, "email": "owner@test.com"}


def _mock_db():
    return AsyncMock()


class TestLogsRoutesAuth:
    """All /api/logs/ endpoints must enforce owner role."""

    @pytest.mark.asyncio
    async def test_users_requires_owner(self):
        from app.api.routes.logs import get_log_users, _membership_svc

        mock_db = _mock_db()
        mock_user = _mock_user()

        _membership_svc.require_role = AsyncMock(
            side_effect=HTTPException(status_code=403, detail="Requires at least 'owner' role")
        )

        mock_request = MagicMock()
        mock_request.app.state.limiter = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_log_users(
                request=mock_request,
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
        from app.api.routes.logs import list_log_requests, _membership_svc

        mock_db = _mock_db()
        mock_user = _mock_user()

        _membership_svc.require_role = AsyncMock(
            side_effect=HTTPException(status_code=403, detail="Not owner")
        )

        mock_request = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await list_log_requests(
                request=mock_request,
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
        from app.api.routes.logs import get_trace_detail, _membership_svc

        mock_db = _mock_db()
        mock_user = _mock_user()

        _membership_svc.require_role = AsyncMock(
            side_effect=HTTPException(status_code=403, detail="Not owner")
        )

        mock_request = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_trace_detail(
                request=mock_request,
                project_id="proj-1",
                trace_id="trace-1",
                db=mock_db,
                user=mock_user,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_summary_requires_owner(self):
        from app.api.routes.logs import get_logs_summary, _membership_svc

        mock_db = _mock_db()
        mock_user = _mock_user()

        _membership_svc.require_role = AsyncMock(
            side_effect=HTTPException(status_code=403, detail="Not owner")
        )

        mock_request = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_logs_summary(
                request=mock_request,
                project_id="proj-1",
                days=7,
                db=mock_db,
                user=mock_user,
            )
        assert exc_info.value.status_code == 403


class TestTraceDetailNotFound:
    @pytest.mark.asyncio
    async def test_returns_404(self):
        from app.api.routes.logs import get_trace_detail, _membership_svc, _logs_svc

        mock_db = _mock_db()
        mock_user = _mock_user()

        _membership_svc.require_role = AsyncMock(return_value="owner")
        _logs_svc.get_trace_detail = AsyncMock(return_value=None)

        mock_request = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_trace_detail(
                request=mock_request,
                project_id="proj-1",
                trace_id="nonexistent",
                db=mock_db,
                user=mock_user,
            )
        assert exc_info.value.status_code == 404
