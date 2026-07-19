import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(default=True)
    is_onboarded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    auth_provider: Mapped[str] = mapped_column(String(20), nullable=False, default="email")
    google_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    picture_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    can_create_projects: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Bumped to invalidate all previously issued JWTs (password change, "sign out
    # everywhere"). Tokens embed the value at mint time; get_current_user rejects on mismatch.
    token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Email verification (F-PROJ-01): email/password registrations start unverified and
    # must not auto-accept email-based invites until the address is proven owned. Google
    # logins are verified by Google (set True on link/create). ``email_verify_token`` holds
    # a SHA-256 hash of the one-time verification token (never the plaintext).
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    email_verify_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Password reset (SCN-013): a one-time reset flow for password-based accounts.
    # ``password_reset_token`` stores a SHA-256 hash of the emailed token (never the
    # plaintext); ``password_reset_expires_at`` bounds its validity. Both are cleared
    # on a successful reset (single-use). Google-only accounts never get a token.
    password_reset_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    password_reset_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
