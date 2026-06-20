"""User-facing CRUD for per-user MCP API keys.

Endpoints:
- ``POST   /api/auth/mcp-tokens``       — issue a new key (plaintext shown once)
- ``GET    /api/auth/mcp-tokens``       — list the caller's keys
- ``DELETE /api/auth/mcp-tokens/{id}``  — revoke

All endpoints require an authenticated user (JWT or session cookie). The
plaintext token is returned exactly once at issue time; the persistence
layer only stores its SHA-256 hash.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, validate_safe_id
from app.core.audit import audit_log
from app.core.rate_limit import limiter
from app.services.mcp_key_service import McpKeyService

logger = logging.getLogger(__name__)
router = APIRouter()
_svc = McpKeyService()


class McpTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    # Optional expiry in days. ``None`` means the token never expires.
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class McpTokenInfo(BaseModel):
    id: str
    name: str
    token_prefix: str
    created_at: str
    last_used_at: str | None
    expires_at: str | None
    revoked_at: str | None


class McpTokenIssued(McpTokenInfo):
    # Plaintext token — returned ONCE at creation, never again.
    token: str


def _to_info(record) -> McpTokenInfo:
    return McpTokenInfo(
        id=record.id,
        name=record.name,
        token_prefix=record.token_prefix,
        created_at=record.created_at.isoformat() if record.created_at else "",
        last_used_at=record.last_used_at.isoformat() if record.last_used_at else None,
        expires_at=record.expires_at.isoformat() if record.expires_at else None,
        revoked_at=record.revoked_at.isoformat() if record.revoked_at else None,
    )


@router.post("/mcp-tokens", response_model=McpTokenIssued)
@limiter.limit("10/minute")
async def create_mcp_token(
    request: Request,
    body: McpTokenCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        issued = await _svc.issue(
            db,
            user_id=user["user_id"],
            name=body.name,
            expires_in_days=body.expires_in_days,
        )
    except ValueError as exc:
        logger.warning(
            "MCP token create: validation rejected for user %s — %s",
            user["user_id"],
            exc,
        )
        raise HTTPException(status_code=400, detail=str(exc))
    audit_log(
        "mcp_token.create",
        user_id=user["user_id"],
        resource_type="mcp_token",
        resource_id=issued.record.id,
    )
    info = _to_info(issued.record)
    return McpTokenIssued(token=issued.plaintext, **info.model_dump())


@router.get("/mcp-tokens", response_model=list[McpTokenInfo])
async def list_mcp_tokens(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    keys = await _svc.list_for_user(db, user["user_id"])
    return [_to_info(k) for k in keys]


@router.delete("/mcp-tokens/{token_id}")
@limiter.limit("30/minute")
async def revoke_mcp_token(
    request: Request,
    token_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    validate_safe_id(token_id, "token_id")
    ok = await _svc.revoke(db, token_id, user["user_id"])
    if not ok:
        logger.info("MCP token revoke: 404 for user %s on token %s", user["user_id"], token_id)
        raise HTTPException(status_code=404, detail="Token not found or already revoked")
    audit_log(
        "mcp_token.revoke",
        user_id=user["user_id"],
        resource_type="mcp_token",
        resource_id=token_id,
    )
    return {"revoked": True}
