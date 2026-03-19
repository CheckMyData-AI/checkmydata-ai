import logging
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)


class AuthService:
    def _hash_password(self, password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def _verify_password(self, plain: str, hashed: str) -> bool:
        return bcrypt.checkpw(plain.encode(), hashed.encode())

    def create_token(self, user_id: str, email: str) -> str:
        now = datetime.now(UTC)
        expire = now + timedelta(minutes=settings.jwt_expire_minutes)
        payload = {"sub": user_id, "email": email, "iat": now, "exp": expire}
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
            password_hash=self._hash_password(password),
            display_name=display_name or email.split("@")[0],
            auth_provider="email",
        )
        session.add(user)
        await session.commit()
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
            logger.warning("Login failed for %s: user not found or no password", email)
            return None
        if not self._verify_password(password, user.password_hash):
            logger.warning("Login failed for %s: invalid credentials", email)
            return None
        logger.info("User logged in: %s (provider=email)", email)
        return user

    async def get_by_id(self, session: AsyncSession, user_id: str) -> User | None:
        result = await session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

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
        return payload

    async def find_or_create_google_user(
        self,
        session: AsyncSession,
        google_payload: dict,
    ) -> User:
        """Find existing user by google_id or email, or create a new one.

        If an email-registered user signs in with Google for the first time,
        their account is linked (google_id stored, auth_provider updated).
        Prioritises google_id match over email match to avoid
        ``MultipleResultsFound`` when both exist as separate rows.
        """
        google_id = google_payload["sub"]
        email = google_payload["email"].lower().strip()
        name = google_payload.get("name", "") or email.split("@")[0]

        gid_result = await session.execute(
            select(User).where(User.google_id == google_id)
        )
        user = gid_result.scalar_one_or_none()

        if user:
            logger.info("User logged in: %s (provider=google)", email)
            return user

        email_result = await session.execute(
            select(User).where(User.email == email)
        )
        user = email_result.scalar_one_or_none()

        if user:
            user.google_id = google_id
            user.auth_provider = "google"
            await session.commit()
            await session.refresh(user)
            logger.info("Google account linked for existing user: %s", email)
            return user

        user = User(
            email=email,
            display_name=name,
            auth_provider="google",
            google_id=google_id,
            password_hash=None,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        logger.info("User registered via Google: %s", email)
        return user
