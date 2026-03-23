from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.audit import audit_log
from app.core.rate_limit import limiter
from app.services.ssh_key_service import SshKeyInUseError, SshKeyService

router = APIRouter()
_svc = SshKeyService()


class SshKeyCreate(BaseModel):
    name: str = Field(max_length=255)
    private_key: str = Field(max_length=16000)
    passphrase: str | None = Field(None, max_length=1024)


class SshKeyResponse(BaseModel):
    id: str
    name: str
    fingerprint: str
    key_type: str
    created_at: str


@router.post("", response_model=SshKeyResponse)
@limiter.limit("10/minute")
async def create_ssh_key(
    request: Request,
    body: SshKeyCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        key = await _svc.create(
            db,
            body.name,
            body.private_key,
            body.passphrase,
            user_id=user["user_id"],
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid SSH key")
    except Exception as e:
        if "UNIQUE constraint" in str(e) or "unique" in str(e).lower():
            raise HTTPException(
                status_code=409, detail=f"SSH key with name '{body.name}' already exists"
            )
        raise
    audit_log(
        "ssh_key.create",
        user_id=user["user_id"],
        resource_type="ssh_key",
        resource_id=key.id,
    )
    return SshKeyResponse(
        id=key.id,
        name=key.name,
        fingerprint=key.fingerprint,
        key_type=key.key_type,
        created_at=key.created_at.isoformat() if key.created_at else "",
    )


@router.get("", response_model=list[SshKeyResponse])
async def list_ssh_keys(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    keys = await _svc.list_all(db, user_id=user["user_id"])
    return [
        SshKeyResponse(
            id=k.id,
            name=k.name,
            fingerprint=k.fingerprint,
            key_type=k.key_type,
            created_at=k.created_at.isoformat() if k.created_at else "",
        )
        for k in keys
    ]


@router.get("/{key_id}", response_model=SshKeyResponse)
async def get_ssh_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    key = await _svc.get(db, key_id, user_id=user["user_id"])
    if not key:
        raise HTTPException(status_code=404, detail="SSH key not found")
    return SshKeyResponse(
        id=key.id,
        name=key.name,
        fingerprint=key.fingerprint,
        key_type=key.key_type,
        created_at=key.created_at.isoformat() if key.created_at else "",
    )


@router.delete("/{key_id}")
@limiter.limit("10/minute")
async def delete_ssh_key(
    request: Request,
    key_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    key = await _svc.get(db, key_id, user_id=user["user_id"])
    if not key:
        raise HTTPException(status_code=404, detail="SSH key not found")
    try:
        deleted = await _svc.delete(db, key_id, user_id=user["user_id"])
    except SshKeyInUseError as e:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete: key is in use by {', '.join(e.references)}",
        )
    if not deleted:
        raise HTTPException(status_code=404, detail="SSH key not found")
    audit_log(
        "ssh_key.delete",
        user_id=user["user_id"],
        resource_type="ssh_key",
        resource_id=key_id,
    )
    return {"ok": True}
