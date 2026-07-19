import asyncio
import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)


def _hash_token(token: str) -> str:
    """SHA-256 hex digest — what we persist for verify/reset tokens (never plaintext)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# Constant bcrypt hash used to equalise login timing for unknown / passwordless
# accounts (F-AUTH-05). Without a dummy verify, the missing-user path returns
# near-instantly while a real account costs ~one bcrypt — a "does this email exist?"
# timing oracle. Computed once at import.
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"timing-equalization", bcrypt.gensalt()).decode()


class AuthService:
    def _hash_password(self, password: str) -> str:
        """Synchronous bcrypt hash. Prefer :meth:`hash_password_async`."""
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def _verify_password(self, plain: str, hashed: str) -> bool:
        """Synchronous bcrypt verify. Prefer :meth:`verify_password_async`."""
        return bcrypt.checkpw(plain.encode(), hashed.encode())

    async def hash_password_async(self, password: str) -> str:
        """Off-thread bcrypt hash (T21).

        bcrypt hashing is CPU-bound (~100ms on modern hardware) and
        previously blocked the event loop, serialising every concurrent
        register/login request. ``asyncio.to_thread`` pushes it to the
        default thread pool.
        """
        return await asyncio.to_thread(self._hash_password, password)

    async def verify_password_async(self, plain: str, hashed: str) -> bool:
        """Off-thread bcrypt verify (T21). See :meth:`hash_password_async`."""
        return await asyncio.to_thread(self._verify_password, plain, hashed)

    def create_token(self, user_id: str, email: str, token_version: int = 0) -> str:
        now = datetime.now(UTC)
        expire = now + timedelta(minutes=settings.jwt_expire_minutes)
        payload = {
            "sub": user_id,
            "email": email,
            "ver": token_version,
            "iat": now,
            "exp": expire,
        }
        return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    def decode_token(self, token: str) -> dict | None:
        try:
            return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        except JWTError:
            return None

    async def register(
        self,
        session: AsyncSession,
        email: str,
        password: str,
        display_name: str = "",
    ) -> User:
        email = email.lower().strip()
        existing = await session.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            logger.warning("Registration failed for %s: email already registered", email)
            raise ValueError("Email already registered")

        user = User(
            email=email,
            password_hash=await self.hash_password_async(password),
            display_name=display_name or email.split("@")[0],
            auth_provider="email",
        )
        session.add(user)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.warning("Registration race for %s: duplicate caught by DB constraint", email)
            raise ValueError("Email already registered")
        await session.refresh(user)
        logger.info("User registered: %s", email)
        return user

    async def authenticate(
        self,
        session: AsyncSession,
        email: str,
        password: str,
    ) -> User | None:
        email = email.lower().strip()
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user or not user.password_hash:
            # Equalise timing (F-AUTH-05): spend ~one bcrypt verify even when there
            # is nothing to check, so the response time doesn't leak account existence.
            await self.verify_password_async(password, _DUMMY_PASSWORD_HASH)
            logger.warning("Login failed for %s: user not found or no password", email)
            return None
        if not await self.verify_password_async(password, user.password_hash):
            logger.warning("Login failed for %s: invalid credentials", email)
            return None
        logger.info("User logged in: %s (provider=email)", email)
        return user

    async def get_by_id(self, session: AsyncSession, user_id: str) -> User | None:
        result = await session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Email verification (F-PROJ-01)
    # ------------------------------------------------------------------

    async def issue_email_verification(self, session: AsyncSession, user: User) -> str:
        """Generate a one-time email-verification token, persist its hash, return plaintext.

        The plaintext is emailed to the user; only the SHA-256 hash is stored, so a
        DB read can't reveal a usable token.
        """
        token = secrets.token_urlsafe(32)
        user.email_verify_token = _hash_token(token)
        await session.commit()
        return token

    async def verify_email(self, session: AsyncSession, token: str) -> User | None:
        """Mark the user owning *token* as verified; clears the token. Returns the user."""
        if not token:
            return None
        token_hash = _hash_token(token)
        result = await session.execute(select(User).where(User.email_verify_token == token_hash))
        user = result.scalar_one_or_none()
        if not user:
            return None
        user.email_verified = True
        user.email_verify_token = None
        await session.commit()
        await session.refresh(user)
        logger.info("Email verified for user: %s", user.email)
        return user

    # ------------------------------------------------------------------
    # Password reset (SCN-013)
    # ------------------------------------------------------------------

    async def issue_password_reset(self, session: AsyncSession, email: str) -> str | None:
        """Mint a one-time password-reset token for a password-based account.

        Returns the RAW token (to be emailed) when a reset was issued, or ``None``
        when there is nothing to reset — the email is unknown, or the account has no
        password (Google-only). Only the SHA-256 hash + expiry are persisted, so a DB
        read can't reveal a usable token. The caller (route) must not leak which case
        occurred (account-enumeration guard).
        """
        email = email.lower().strip()
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user or not user.password_hash:
            # No password-based account to reset. Return None; the route still
            # responds with a generic success so existence isn't leaked.
            return None

        token = secrets.token_urlsafe(32)
        user.password_reset_token = _hash_token(token)
        user.password_reset_expires_at = datetime.now(UTC) + timedelta(
            hours=settings.password_reset_expiry_hours
        )
        await session.commit()
        logger.info("Password reset issued for user: %s", user.email)
        return token

    async def reset_password(self, session: AsyncSession, token: str, new_password: str) -> bool:
        """Consume *token* and set *new_password*. Returns True on success.

        Finds the account whose stored hash matches *token* AND whose expiry has not
        passed, sets the new password, clears the token+expiry (single-use), and bumps
        ``token_version`` to revoke every previously issued session (the "reset my
        password" action must lock out any stolen/leaked token). Raises ``ValueError``
        for a missing / invalid / expired token — mirroring the bad-token handling
        elsewhere in this service.
        """
        if not token:
            raise ValueError("Invalid or expired password reset token")
        token_hash = _hash_token(token)
        result = await session.execute(select(User).where(User.password_reset_token == token_hash))
        user = result.scalar_one_or_none()
        if not user or not user.password_reset_expires_at:
            raise ValueError("Invalid or expired password reset token")

        expires_at = user.password_reset_expires_at
        # Rows written by SQLite come back naive; treat them as UTC for comparison.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < datetime.now(UTC):
            raise ValueError("Invalid or expired password reset token")

        user.password_hash = await self.hash_password_async(new_password)
        user.password_reset_token = None
        user.password_reset_expires_at = None
        # Revoke all previously issued tokens (parity with change_password): a reset
        # is the canonical "I lost access / was compromised" action.
        user.token_version = (user.token_version or 0) + 1
        await session.commit()
        logger.info("Password reset completed for user: %s (token_version bumped)", user.email)
        return True

    # ------------------------------------------------------------------
    # Google OAuth
    # ------------------------------------------------------------------

    def verify_google_token(self, credential: str) -> dict:
        """Verify a Google ID token and return the payload.

        Raises ``ValueError`` on invalid/expired tokens.
        """
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        if not settings.google_client_id:
            raise ValueError("Google OAuth is not configured")

        payload = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            settings.google_client_id,
        )

        if not payload.get("email_verified", False):
            raise ValueError("Google account email is not verified")

        return payload

    async def find_or_create_google_user(
        self,
        session: AsyncSession,
        google_payload: dict,
    ) -> tuple[User, bool]:
        """Find existing user by google_id or email, or create a new one.

        Returns ``(user, created)`` where *created* is True when a brand-new
        account was created (used to trigger the welcome email).

        If an email-registered user signs in with Google for the first time,
        their account is linked (google_id stored, auth_provider updated).
        Prioritises google_id match over email match to avoid
        ``MultipleResultsFound`` when both exist as separate rows.
        """
        google_id = google_payload["sub"]
        email = google_payload["email"].lower().strip()
        name = google_payload.get("name", "") or email.split("@")[0]
        picture = google_payload.get("picture")

        gid_result = await session.execute(select(User).where(User.google_id == google_id))
        user = gid_result.scalar_one_or_none()

        if user:
            if picture and user.picture_url != picture:
                user.picture_url = picture
                await session.commit()
                await session.refresh(user)
            logger.info("User logged in: %s (provider=google)", email)
            return user, False

        email_result = await session.execute(select(User).where(User.email == email))
        user = email_result.scalar_one_or_none()

        if user:
            user.google_id = google_id
            # F-AUTH-07: don't wipe an existing avatar when Google sends no picture,
            # and don't misreport auth_provider — a password user keeps "email"
            # (password login still works) while gaining the linked google_id.
            if picture:
                user.picture_url = picture
            if user.password_hash is None:
                user.auth_provider = "google"
            # F-PROJ-01: Google proved ownership of this address.
            user.email_verified = True
            await session.commit()
            await session.refresh(user)
            logger.info("Google account linked for existing user: %s", email)
            return user, False

        user = User(
            email=email,
            display_name=name,
            auth_provider="google",
            google_id=google_id,
            picture_url=picture,
            password_hash=None,
            email_verified=True,  # F-PROJ-01: Google-verified address.
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        logger.info("User registered via Google: %s", email)
        return user, True
