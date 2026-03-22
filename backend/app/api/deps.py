import re
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

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
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Extract and validate JWT from Authorization header.

    Returns a dict with ``user_id`` and ``email``.
    Raises 401 if the token is missing, invalid, or the user is inactive.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    from app.services.auth_service import AuthService

    token = authorization.removeprefix("Bearer ")
    auth = AuthService()
    payload = auth.decode_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = await auth.get_by_id(db, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    return {"user_id": user.id, "email": user.email}
