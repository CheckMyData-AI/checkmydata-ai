"""Per-user MCP API key issuance, lookup, and revocation.

Tokens are random 32-byte URL-safe strings prefixed with ``cmd_mcp_`` so
they are identifiable in logs and config files. Only the SHA-256 hash is
persisted; the plaintext is returned to the user exactly once at issue
time. ``lookup_by_token`` is constant-time over the candidate hash and
returns ``None`` for unknown / revoked / expired keys so the MCP auth path
fails closed without leaking which condition was hit.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mcp_api_key import McpApiKey

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "cmd_mcp_"
TOKEN_RANDOM_BYTES = 32
DISPLAY_PREFIX_LEN = 12  # "cmd_mcp_ABCD" — 4 chars of randomness shown


def _hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _generate_plaintext() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_RANDOM_BYTES)


@dataclass
class IssuedKey:
    """Returned from ``issue`` — includes plaintext (shown to user once)."""

    record: McpApiKey
    plaintext: str


class McpKeyService:
    async def issue(
        self,
        session: AsyncSession,
        user_id: str,
        name: str,
        expires_in_days: int | None = None,
    ) -> IssuedKey:
        if not user_id:
            raise ValueError("user_id is required to issue an MCP key")
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("name is required")
        if len(clean_name) > 255:
            raise ValueError("name must be 255 characters or fewer")

        plaintext = _generate_plaintext()
        token_hash = _hash_token(plaintext)
        expires_at: datetime | None = None
        if expires_in_days is not None:
            if expires_in_days <= 0:
                raise ValueError("expires_in_days must be positive")
            expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)

        record = McpApiKey(
            user_id=user_id,
            name=clean_name,
            token_hash=token_hash,
            token_prefix=plaintext[:DISPLAY_PREFIX_LEN],
            expires_at=expires_at,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        logger.info(
            "MCP key issued for user %s (id=%s, name=%r, expires_at=%s)",
            user_id,
            record.id,
            clean_name,
            expires_at.isoformat() if expires_at else "never",
        )
        return IssuedKey(record=record, plaintext=plaintext)

    async def list_for_user(self, session: AsyncSession, user_id: str) -> list[McpApiKey]:
        if not user_id:
            return []
        result = await session.execute(
            select(McpApiKey)
            .where(McpApiKey.user_id == user_id)
            .order_by(McpApiKey.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_for_user(
        self, session: AsyncSession, key_id: str, user_id: str
    ) -> McpApiKey | None:
        result = await session.execute(
            select(McpApiKey).where(
                McpApiKey.id == key_id,
                McpApiKey.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def revoke(self, session: AsyncSession, key_id: str, user_id: str) -> bool:
        key = await self.get_for_user(session, key_id, user_id)
        if key is None:
            logger.warning(
                "MCP key revoke: user %s tried to revoke non-existent or non-owned key %s",
                user_id,
                key_id,
            )
            return False
        if key.revoked_at is not None:
            logger.info(
                "MCP key revoke: key %s already revoked, no-op for user %s",
                key_id,
                user_id,
            )
            return False
        key.revoked_at = datetime.now(UTC)
        await session.commit()
        logger.info("MCP key revoked: id=%s user=%s", key_id, user_id)
        return True

    async def lookup_by_token(self, session: AsyncSession, plaintext: str) -> McpApiKey | None:
        """Return the live key matching ``plaintext`` or ``None``.

        ``None`` covers unknown tokens, revoked keys, and expired keys —
        the caller MUST NOT distinguish these cases to avoid leaking the
        validity of a guessed token.
        """
        if not plaintext or not plaintext.startswith(TOKEN_PREFIX):
            return None
        token_hash = _hash_token(plaintext)
        result = await session.execute(select(McpApiKey).where(McpApiKey.token_hash == token_hash))
        key = result.scalar_one_or_none()
        if key is None:
            logger.debug("MCP key lookup: no record for hash prefix %s", token_hash[:8])
            return None
        if key.revoked_at is not None:
            logger.info("MCP key lookup: id=%s is revoked", key.id)
            return None
        if key.expires_at is not None:
            expires_at = key.expires_at
            if expires_at.tzinfo is None:
                # SQLite reads a DateTime(timezone=True) column back as naive;
                # stored timestamps are UTC, so attach UTC before comparing —
                # otherwise ``naive <= aware`` raises TypeError and breaks auth
                # for every valid expiring token after a process restart.
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= datetime.now(UTC):
                logger.info(
                    "MCP key lookup: id=%s expired at %s",
                    key.id,
                    expires_at.isoformat(),
                )
                return None
        # Best-effort touch; failure here must not deny the call.
        try:
            key.last_used_at = datetime.now(UTC)
            await session.commit()
        except Exception:
            logger.warning(
                "MCP key lookup: failed to touch last_used_at for id=%s", key.id, exc_info=True
            )
            await session.rollback()
        return key
