"""Owner-scoped, reusable credentials for external analytics vendors (spec §1.1).

Deliberately mirrors :class:`app.models.ssh_key.SshKey`: one encrypted secret per
row, owned by a user, referenced by any number of connections. The plaintext (a
Google service-account JSON, an App Store Connect ``.p8`` PEM, …) is Fernet
ciphertext in ``secret_encrypted`` and **appears in no response model**;
``fingerprint`` exists so the UI can answer "is this the same key?" without ever
handing the key back.

``user_id`` is nullable so trusted internal/seeded rows can exist, but the
service layer is owner-strict: a request carrying a ``user_id`` filters on
equality and never unions ``user_id IS NULL`` — see ``ssh_key_service``
(F-SSH-06) for the same rule and the reason behind it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class VendorCredential(Base):
    __tablename__ = "vendor_credentials"
    __table_args__ = (Index("ix_vendor_credentials_user_provider", "user_id", "provider"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # "ga4" | "appstore" | "googleplay"
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    # Fernet ciphertext of the vendor secret. Never serialised, never logged.
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    # First 16 hex chars of sha256(plaintext) — an identity hint, not the key.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # Non-secret extras surfaced in the UI (e.g. a service account's client_email).
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
