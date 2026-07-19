import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.config import settings
from app.core.audit import audit_log
from app.core.auth_cookies import clear_session_cookies, set_session_cookies
from app.core.rate_limit import limiter
from app.services.auth_service import AuthService
from app.services.email_service import EmailService
from app.services.invite_service import InviteService

logger = logging.getLogger(__name__)

router = APIRouter()
_auth = AuthService()
_invite_svc = InviteService()
_email_svc = EmailService()


def _auth_response(user, token: str) -> "AuthResponse":  # noqa: ANN001
    """Build the auth response.

    Under cookie auth the JWT is omitted from the JSON body (F-AUTH-04) so the SPA
    relies solely on the httpOnly cookie (no token for XSS to read / for the SPA to
    persist). Non-browser Bearer clients (cookie auth off) still receive it.
    """
    return AuthResponse(
        token="" if settings.auth_cookie_enabled else token,
        expires_in=settings.jwt_expire_minutes * 60,
        user={
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "picture_url": user.picture_url,
            "auth_provider": user.auth_provider,
            "is_onboarded": user.is_onboarded,
            "can_create_projects": user.can_create_projects,
            # F-PROJ-01: the SPA surfaces a "verify your email" prompt when this is
            # False for a non-Google account (Google logins are pre-verified).
            "email_verified": user.email_verified,
        },
    )


class RegisterRequest(BaseModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class GoogleLoginRequest(BaseModel):
    credential: str
    g_csrf_token: str | None = None
    nonce: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128)


class AuthResponse(BaseModel):
    token: str
    user: dict
    # Session lifetime in seconds. Non-sensitive (it's just jwt_expire_minutes) and
    # lets the SPA schedule proactive refresh without reading the JWT — required
    # because under cookie auth `token` is empty (F-AUTH-04).
    expires_in: int = 0


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    picture_url: str | None = None
    auth_provider: str = "email"
    is_onboarded: bool = False
    can_create_projects: bool = False
    email_verified: bool = False


@router.post("/register", response_model=AuthResponse)
@limiter.limit("5/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    try:
        user = await _auth.register(db, body.email, body.password, body.display_name)
    except ValueError as e:
        logger.info("Registration conflict: %s", e)
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists.",
        ) from e

    # F-PROJ-01: an email/password registration is NOT proof the registrant owns the
    # address, so we do NOT auto-accept email-based invites here. A verification link is
    # sent; pending invites are auto-accepted only once the address is verified (below).
    audit_log("auth.register", user_id=user.id, detail=user.email)
    verify_token = await _auth.issue_email_verification(db, user)
    await _email_svc.send_verification_email(
        user_id=user.id, email=user.email, token=verify_token, display_name=user.display_name
    )
    await _email_svc.send_welcome_email(
        user_id=user.id, email=user.email, display_name=user.display_name
    )
    token = _auth.create_token(user.id, user.email, user.token_version)
    if settings.auth_cookie_enabled:
        set_session_cookies(response, token)
    return _auth_response(user, token)


@router.post("/verify-email")
@limiter.limit("10/minute")
async def verify_email(
    request: Request,
    body: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Confirm an email address (F-PROJ-01). On success, auto-accept the now-verified
    user's pending email-based invites."""
    user = await _auth.verify_email(db, body.token)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")
    members = await _invite_svc.auto_accept_for_user(db, user.id, user.email)
    audit_log("auth.verify_email", user_id=user.id, detail=user.email)
    return {"ok": True, "invites_accepted": len(members)}


@router.post("/resend-verification")
@limiter.limit("3/minute")
async def resend_verification(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-issue and re-send the email-verification link for the current user (F-PROJ-01).

    Idempotent no-op when there is nothing to verify: Google accounts prove their
    address through Google, and an already-verified email account has no pending
    verification. In both cases we return ``already_verified: True`` without minting
    a new token or sending mail (so the endpoint can't be used as an email-spam relay).
    """
    user = await _auth.get_by_id(db, current_user["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.auth_provider == "google" or user.email_verified:
        return {"ok": True, "already_verified": True}

    verify_token = await _auth.issue_email_verification(db, user)
    await _email_svc.send_verification_email(
        user_id=user.id, email=user.email, token=verify_token, display_name=user.display_name
    )
    audit_log("auth.resend_verification", user_id=user.id, detail=user.email)
    return {"ok": True, "already_verified": False}


@router.post("/login", response_model=AuthResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    user = await _auth.authenticate(db, body.email, body.password)
    if not user:
        audit_log("auth.login_failed", detail=body.email)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    audit_log("auth.login", user_id=user.id, detail=user.email)
    token = _auth.create_token(user.id, user.email, user.token_version)
    if settings.auth_cookie_enabled:
        set_session_cookies(response, token)
    return _auth_response(user, token)


@router.post("/google", response_model=AuthResponse)
@limiter.limit("10/minute")
async def google_login(
    request: Request,
    body: GoogleLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    # F-AUTH-06: enforce the double-submit based on the *cookie*, not the body. If
    # Google set the g_csrf_token cookie, a matching body token is required — omitting
    # it (the old bypass) is now rejected.
    cookie_token = request.cookies.get("g_csrf_token")
    if cookie_token and (not body.g_csrf_token or cookie_token != body.g_csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token mismatch")

    try:
        payload = _auth.verify_google_token(body.credential)
    except ValueError as exc:
        logger.warning("Google token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid Google token") from exc

    if body.nonce:
        token_nonce = payload.get("nonce")
        if not token_nonce or token_nonce != body.nonce:
            logger.warning("Google nonce mismatch: expected=%s got=%s", body.nonce, token_nonce)
            raise HTTPException(status_code=401, detail="Invalid nonce in Google token")

    user, is_new_user = await _auth.find_or_create_google_user(db, payload)

    await _invite_svc.auto_accept_for_user(db, user.id, user.email)

    audit_log("auth.google", user_id=user.id, detail=user.email)
    if is_new_user:
        await _email_svc.send_welcome_email(
            user_id=user.id, email=user.email, display_name=user.display_name
        )
    token = _auth.create_token(user.id, user.email, user.token_version)
    if settings.auth_cookie_enabled:
        set_session_cookies(response, token)
    return _auth_response(user, token)


@router.post("/change-password")
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    response: Response,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = await _auth.get_by_id(db, current_user["user_id"])
    if not user or not user.password_hash:
        raise HTTPException(
            status_code=400,
            detail="Password login is not enabled for this account",
        )
    # Off-thread bcrypt (F-AUTH-03): the sync path stalled the event loop ~200ms/call.
    if not await _auth.verify_password_async(body.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    user.password_hash = await _auth.hash_password_async(body.new_password)
    # Revoke all previously issued tokens (F-AUTH-02): the canonical "I've been
    # compromised" action must lock out any stolen/leaked session, cookie or Bearer.
    user.token_version = (user.token_version or 0) + 1
    await db.commit()
    # Keep the *current* session valid by re-issuing a cookie at the new version;
    # every other outstanding token is now rejected by get_current_user.
    if settings.auth_cookie_enabled:
        set_session_cookies(response, _auth.create_token(user.id, user.email, user.token_version))
    audit_log("auth.change_password", user_id=user.id, detail=user.email)
    logger.info("Password changed for user %s (token_version bumped)", user.email)
    return {"ok": True}


@router.post("/refresh", response_model=AuthResponse)
@limiter.limit("30/minute")
async def refresh_token(
    request: Request,
    response: Response,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Issue a fresh JWT for an already-authenticated user. Rate-limited (F-AUTH-09):
    it is a token-minting endpoint and must be bounded."""
    user = await _auth.get_by_id(db, current_user["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    token = _auth.create_token(user.id, user.email, user.token_version)
    if settings.auth_cookie_enabled:
        set_session_cookies(response, token)
    audit_log("auth.refresh", user_id=user.id, detail=user.email)  # F-AUTH-16
    return _auth_response(user, token)


@router.post("/logout")
async def logout(
    response: Response,
    request: Request,
):
    """Clear the browser session + CSRF cookies.

    Safe to call unauthenticated (idempotent) so the SPA can always reach a
    clean logged-out state even with an expired session.
    """
    clear_session_cookies(response)
    # F-AUTH-16: best-effort audit (logout may be unauthenticated, so resolve the
    # subject from the session cookie if present without failing the request).
    subject = None
    try:
        from app.core.auth_cookies import SESSION_COOKIE

        cookie_token = request.cookies.get(SESSION_COOKIE)
        if cookie_token:
            payload = _auth.decode_token(cookie_token)
            subject = payload.get("sub") if payload else None
    except Exception:
        subject = None
    audit_log("auth.logout", user_id=subject)
    return {"ok": True}


@router.get("/me", response_model=UserResponse)
async def me(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current user profile. Used by the frontend on session restore."""
    user = await _auth.get_by_id(db, current_user["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        picture_url=user.picture_url,
        auth_provider=user.auth_provider,
        is_onboarded=user.is_onboarded,
        can_create_projects=user.can_create_projects,
        email_verified=user.email_verified,
    )


@router.post("/complete-onboarding")
async def complete_onboarding(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = await _auth.get_by_id(db, current_user["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    user.is_onboarded = True
    await db.commit()
    return {"ok": True}


@router.delete("/account")
@limiter.limit("3/minute")
async def delete_account(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete the current user and all associated data."""
    from sqlalchemy import delete, select

    from app.models.connection import Connection
    from app.models.mcp_api_key import McpApiKey
    from app.models.project import Project
    from app.models.project_member import ProjectMember
    from app.models.user import User
    from app.services.indexing_artifacts import (
        cleanup_connection_artifacts,
        cleanup_project_artifacts,
    )

    user_id = current_user["user_id"]
    email = current_user.get("email", "")

    # Enumerate owned projects + their connections BEFORE deletion so we can clean up
    # the on-disk artifacts (ChromaDB collection, BM25 snapshots) that DB FK cascade
    # cannot reach (F-AUTH-10).
    owned_ids = (
        (await db.execute(select(Project.id).where(Project.owner_id == user_id))).scalars().all()
    )
    connection_ids: list[str] = []
    if owned_ids:
        connection_ids = list(
            (await db.execute(select(Connection.id).where(Connection.project_id.in_(owned_ids))))
            .scalars()
            .all()
        )

    async with db.begin_nested():
        if owned_ids:
            await db.execute(delete(Project).where(Project.id.in_(owned_ids)))
        # Explicit MCP-key revocation (defensive; FK cascade also covers it now that
        # SQLite FKs are enforced — F-AUTH-01).
        await db.execute(delete(McpApiKey).where(McpApiKey.user_id == user_id))
        await db.execute(delete(ProjectMember).where(ProjectMember.user_id == user_id))
        await db.execute(delete(User).where(User.id == user_id))

    await db.commit()

    # Best-effort on-disk cleanup (idempotent, never throws) after the DB delete commits.
    for cid in connection_ids:
        cleanup_connection_artifacts(cid)
    for pid in owned_ids:
        cleanup_project_artifacts(pid)

    audit_log("auth.delete_account", user_id=user_id, detail=email)
    logger.info(
        "Account deleted: user_id=%s (projects=%d, connections=%d)",
        user_id,
        len(owned_ids),
        len(connection_ids),
    )
    return {"ok": True}
