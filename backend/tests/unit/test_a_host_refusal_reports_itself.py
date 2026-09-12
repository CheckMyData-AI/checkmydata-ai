"""The host re-check reports itself, instead of blaming the password (review, 2026-09-12).

`SQL-07` moved the DNS-rebinding guard into `ConnectionService.to_config`, which is
right — that is the one funnel every query, index and health check passes through. What
it did not account for is that `HostNotAllowedError` **subclasses `ValueError`**, and
`to_config`'s callers already catch `ValueError` to mean one specific thing.

So a rebinding refusal arrived at the user as:

    Cannot decrypt credentials for connection 'prod'.
    Please re-enter the password in Settings → Connections.

They would re-enter it, it would fail again, and nothing anywhere would say that the
host now resolves to an address connections may not reach. That is the same shape this
whole remediation is about: a message asserting something the system never checked.

Two fixes, and the order matters. `_safe_to_config` re-raises the host error rather than
translating it, and `main.py` registers a handler for it **before** the generic
`ValueError` one, so every route answers 422 with the guard's own sentence rather than a
500 with none.
"""

from __future__ import annotations

import pytest


class TestAHostRefusalSaysWhatItIs:
    async def test_the_chat_path_does_not_call_it_a_password_problem(self) -> None:
        from unittest.mock import AsyncMock, patch

        from app.api.routes.chat import _safe_to_config
        from app.connectors.host_guard import HostNotAllowedError

        refusal = HostNotAllowedError(
            "db_host 'db.attacker.test' resolves to a non-public address (169.254.169.254)."
        )
        conn = type("Conn", (), {"name": "prod"})()

        with patch("app.api.routes.chat._conn_svc.to_config", new=AsyncMock(side_effect=refusal)):
            with pytest.raises(Exception) as exc:
                await _safe_to_config(AsyncMock(), conn)

        detail = str(getattr(exc.value, "detail", exc.value))
        assert "decrypt" not in detail.lower() and "password" not in detail.lower(), (
            "`HostNotAllowedError` IS a `ValueError`, so the decryption branch claimed "
            "it: the product told the user to re-enter a password that was never the "
            f"problem. {detail!r}"
        )
        assert "169.254.169.254" in detail or "resolves" in detail, (
            f"the guard's own sentence is what the user needs to act on: {detail!r}"
        )

    async def test_a_real_decryption_failure_still_says_so(self) -> None:
        """The branch that was right must stay right."""
        from unittest.mock import AsyncMock, patch

        from fastapi import HTTPException

        from app.api.routes.chat import _safe_to_config

        conn = type("Conn", (), {"name": "prod"})()
        with patch(
            "app.api.routes.chat._conn_svc.to_config",
            new=AsyncMock(side_effect=ValueError("Cannot decrypt credentials for 'prod'")),
        ):
            with pytest.raises(HTTPException) as exc:
                await _safe_to_config(AsyncMock(), conn)
        assert exc.value.status_code == 400
        assert "password" in str(exc.value.detail).lower()

    def test_the_app_answers_a_host_refusal_with_its_own_words(self) -> None:
        """Registered for every route at once — `to_config` has 35 call sites."""
        from app.connectors.host_guard import HostNotAllowedError
        from app.main import app

        assert HostNotAllowedError in app.exception_handlers, (
            "without a handler of its own, a host refusal falls to the generic "
            "`ValueError` handler, which re-raises everything it does not recognise — "
            "a 500 with no message, on every one of `to_config`'s 35 call sites"
        )

    async def test_that_handler_returns_a_client_error_not_a_server_one(self) -> None:
        from fastapi import Request

        from app.connectors.host_guard import HostNotAllowedError
        from app.main import app

        handler = app.exception_handlers[HostNotAllowedError]
        response = await handler(
            Request({"type": "http", "method": "GET", "path": "/", "headers": []}),
            HostNotAllowedError("db_host 'x' resolves to a non-public address (10.0.0.1)."),
        )
        assert response.status_code == 422, (
            "the caller's stored configuration is what is wrong, and they can fix it — "
            "a 5xx says the server broke"
        )
        assert b"10.0.0.1" in response.body
