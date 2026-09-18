"""C-05: testing a connection answers, and retries what the drivers actually raise.

`POST /connections/{id}/test` against an unreachable bastion held the request for about
**fourteen minutes**: the tunnel retried twice, the manager three times and the service
three times, at a 45 s handshake each. And the service's retry caught
`(TimeoutError, ConnectionError, OSError)` — PyMySQL raises `OperationalError` for a
refused socket, which is none of those, so the engine most often reached through a
bastion was the one never retried.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.connectors.transient_errors import TRANSIENT_CONNECT_ERRORS


def test_the_drivers_own_connection_errors_are_retryable():
    import pymysql.err

    # The one that mattered: this deployment's MySQL connections raise it for a refused
    # socket, a lost connection and a handshake timeout.
    assert pymysql.err.OperationalError in TRANSIENT_CONNECT_ERRORS
    assert TimeoutError in TRANSIENT_CONNECT_ERRORS
    assert ConnectionError in TRANSIENT_CONNECT_ERRORS


def test_an_authentication_failure_is_not_retryable():
    import pymysql.err

    # Retrying a wrong password spends the budget and can never succeed; it is also how
    # an account gets locked. `OperationalError` covers the transport, not the credential.
    assert pymysql.err.ProgrammingError not in TRANSIENT_CONNECT_ERRORS
    assert ValueError not in TRANSIENT_CONNECT_ERRORS


def test_the_ceiling_is_configured_and_positive():
    assert settings.connection_test_timeout_seconds > 0


def test_a_zero_ceiling_is_refused_at_boot(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("CONNECTION_TEST_TIMEOUT_SECONDS", "0")
    with pytest.raises(ValueError, match="CONNECTION_TEST_TIMEOUT_SECONDS"):
        Settings()


def _request():
    """A real `Request`: the route carries a rate limiter that inspects one."""
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/connections/c1/test",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
            "app": SimpleNamespace(state=SimpleNamespace()),
        }
    )


@pytest.mark.asyncio
async def test_a_test_that_hangs_is_answered_not_awaited(monkeypatch):
    """The route reports the timeout: "we could not reach it" is the answer it owes."""
    from app.api.routes import connections as routes

    monkeypatch.setattr(settings, "connection_test_timeout_seconds", 1)

    async def never(*_a, **_kw):
        await asyncio.sleep(3600)

    conn = SimpleNamespace(
        id="c1", project_id="p1", source_type="database", db_type="mysql", name="Conn"
    )
    with (
        patch.object(routes._svc, "get", new=AsyncMock(return_value=conn)),
        patch.object(routes._svc, "test_connection", new=never),
        patch.object(routes._membership_svc, "require_role", new=AsyncMock(return_value="owner")),
    ):
        started = asyncio.get_running_loop().time()
        result = await routes.test_connection(
            request=_request(),
            connection_id="c1",
            db=AsyncMock(),
            user={"user_id": "u1"},
        )
        elapsed = asyncio.get_running_loop().time() - started

    assert result["success"] is False
    assert "90s" not in result["error"], "the message quotes the configured ceiling"
    assert "1s" in result["error"]
    assert elapsed < 5, f"the route waited {elapsed:.1f}s on a ceiling of 1s"


@pytest.mark.asyncio
async def test_a_tunnelled_connect_is_attempted_once_here(monkeypatch):
    """Through a bastion the retry belongs to the tunnel, which already has one."""
    from app.services.connection_service import ConnectionService

    attempts = 0

    class _Connector:
        async def connect(self, _config):
            nonlocal attempts
            attempts += 1
            raise TimeoutError("bastion unreachable")

        async def disconnect(self):
            pass

    svc = ConnectionService()
    conn = SimpleNamespace(
        id="c1",
        name="Tunnelled",
        source_type="database",
        db_type="mysql",
        project_id="p1",
    )
    config = SimpleNamespace(ssh_host="bastion.example.com", ssh_exec_mode=False)

    with (
        patch.object(svc, "get", new=AsyncMock(return_value=conn)),
        patch.object(svc, "to_config", new=AsyncMock(return_value=config)),
        patch(
            "app.services.connection_service.get_connector",
            return_value=_Connector(),
        ),
    ):
        result = await svc.test_connection(AsyncMock(), "c1")

    assert attempts == 1, f"the service retried a tunnelled connect {attempts} times"
    assert result["success"] is False
