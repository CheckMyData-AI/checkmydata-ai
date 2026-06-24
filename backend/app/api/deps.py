import hmac
import re
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth_cookies import CSRF_COOKIE, CSRF_HEADER, SAFE_METHODS, SESSION_COOKIE
from app.models.base import async_session_factory

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


def validate_safe_id(value: str, name: str = "id") -> str:
    """Reject path-parameter values that could cause path traversal."""
    if not _SAFE_ID_RE.match(value):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {name}: must be alphanumeric, dash, or underscore (max 128 chars)",
        )
    return value


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


async def get_current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Extract and validate the JWT from the Authorization header or session cookie.

    Browsers authenticate via the ``httpOnly`` session cookie (T-SEC-3); other
    API clients keep using ``Authorization: Bearer``. Returns a dict with
    ``user_id`` and ``email``. Raises 401 if the token is missing, invalid, or
    the user is inactive, and 403 if a cookie-authenticated mutation fails CSRF.
    """
    token: str | None = None
    auth_via_cookie = False
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
    else:
        cookie_token = request.cookies.get(SESSION_COOKIE)
        if cookie_token:
            token = cookie_token
            auth_via_cookie = True

    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    # CSRF only applies to cookie auth (the browser auto-sends the cookie). Bearer
    # clients set the header explicitly and are not vulnerable to CSRF.
    if auth_via_cookie and request.method not in SAFE_METHODS:
        header_csrf = request.headers.get(CSRF_HEADER)
        cookie_csrf = request.cookies.get(CSRF_COOKIE)
        if not header_csrf or not cookie_csrf or not hmac.compare_digest(header_csrf, cookie_csrf):
            raise HTTPException(status_code=403, detail="CSRF token missing or invalid")

    from app.services.auth_service import AuthService

    auth = AuthService()
    payload = auth.decode_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = await auth.get_by_id(db, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # Token revocation: a JWT carries the user's token_version at mint time. Bumping
    # the column (password change, "sign out everywhere") invalidates all prior tokens.
    # ``ver`` defaults to 0 for tokens minted before this claim existed (no forced logout).
    if payload.get("ver", 0) != user.token_version:
        raise HTTPException(status_code=401, detail="Session expired, please sign in again")

    return {"user_id": user.id, "email": user.email}


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Only allow users whose email is in ``settings.admin_emails``.

    Returns the same dict as :func:`get_current_user` on success. Raises
    403 otherwise. Configure admins via ``ADMIN_EMAILS`` env var.
    """
    if not settings.is_admin_email(user.get("email")):
        raise HTTPException(
            status_code=403,
            detail="Admin privileges required for this endpoint.",
        )
    return user
