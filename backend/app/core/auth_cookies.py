"""Browser session cookie + CSRF helpers (T-SEC-3 / F-SEC-3).

The browser receives the session JWT as an ``httpOnly`` cookie so it can never
be read by JavaScript (no XSS token theft, nothing in ``localStorage``). Because
the browser auto-sends cookies, cookie-authenticated *mutations* are protected
with a double-submit CSRF token: a second, non-httpOnly cookie that the SPA
reads and echoes back in the ``X-CSRF-Token`` header. The server checks the two
match.

Non-browser API clients keep using ``Authorization: Bearer`` and are exempt from
CSRF (they never send the cookie automatically).
"""

from __future__ import annotations

import secrets
from typing import Literal

from fastapi import Response

from app.config import settings

SESSION_COOKIE = "cmd_session"
CSRF_COOKIE = "cmd_csrf"
CSRF_HEADER = "x-csrf-token"

# HTTP methods that do not mutate state and therefore need no CSRF check.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def _max_age() -> int:
    return settings.jwt_expire_minutes * 60


def _samesite() -> Literal["lax", "strict", "none"]:
    value = (settings.auth_cookie_samesite or "lax").lower()
    if value in ("lax", "strict", "none"):
        return value  # type: ignore[return-value]
    return "lax"


def set_session_cookies(response: Response, token: str) -> str:
    """Attach the session + CSRF cookies to ``response``. Returns the CSRF token.

    The session cookie is httpOnly (hidden from JS); the CSRF cookie is readable
    so the SPA can echo it back in a header on state-changing requests.
    """
    max_age = _max_age()
    secure = settings.auth_cookie_secure
    samesite = _samesite()
    domain = settings.auth_cookie_domain or None

    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite=samesite,
        domain=domain,
        path="/",
    )
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,  # must be readable by the SPA for the double-submit
        secure=secure,
        samesite=samesite,
        domain=domain,
        path="/",
    )
    return csrf_token


def clear_session_cookies(response: Response) -> None:
    domain = settings.auth_cookie_domain or None
    response.delete_cookie(SESSION_COOKIE, path="/", domain=domain)
    response.delete_cookie(CSRF_COOKIE, path="/", domain=domain)
