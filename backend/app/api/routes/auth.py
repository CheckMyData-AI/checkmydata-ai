import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.rate_limit import limiter
from app.services.auth_service import AuthService
from app.services.invite_service import InviteService

logger = logging.getLogger(__name__)

router = APIRouter()
_auth = AuthService()
_invite_svc = InviteService()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleLoginRequest(BaseModel):
    credential: str


class AuthResponse(BaseModel):
    token: str
    user: dict


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str


@router.post("/register", response_model=AuthResponse)
@limiter.limit("5/minute")
async def register(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    try:
        user = await _auth.register(db, body.email, body.password, body.display_name)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    await _invite_svc.auto_accept_for_user(db, user.id, user.email)

    token = _auth.create_token(user.id, user.email)
    return AuthResponse(
        token=token,
        user={"id": user.id, "email": user.email, "display_name": user.display_name},
    )


@router.post("/login", response_model=AuthResponse)
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await _auth.authenticate(db, body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = _auth.create_token(user.id, user.email)
    return AuthResponse(
        token=token,
        user={"id": user.id, "email": user.email, "display_name": user.display_name},
    )


@router.post("/google", response_model=AuthResponse)
@limiter.limit("10/minute")
async def google_login(
    request: Request, body: GoogleLoginRequest, db: AsyncSession = Depends(get_db),
):
    try:
        payload = _auth.verify_google_token(body.credential)
    except ValueError as exc:
        logger.warning("Google token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid Google token") from exc

    user = await _auth.find_or_create_google_user(db, payload)

    await _invite_svc.auto_accept_for_user(db, user.id, user.email)

    token = _auth.create_token(user.id, user.email)
    return AuthResponse(
        token=token,
        user={"id": user.id, "email": user.email, "display_name": user.display_name},
    )
