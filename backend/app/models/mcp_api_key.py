"""Per-user MCP API key.

Each user can mint one or more MCP API keys to authenticate their personal
MCP clients (Claude Desktop, Cursor, custom). The token plaintext is shown
exactly once at issue time; only a SHA-256 hash is persisted. A short prefix
(`cmd_mcp_xxxx…`) is stored to let the UI identify the key without exposing
the secret.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class McpApiKey(Base):
    __tablename__ = "mcp_api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # SHA-256 hex digest of the plaintext token. We never store the secret.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    # First 12 chars of the plaintext (cmd_mcp_xxxx…) for display only.
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
