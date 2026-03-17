from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.services.ssh_key_service import SshKeyInUseError, SshKeyService

router = APIRouter()
_svc = SshKeyService()


class SshKeyCreate(BaseModel):
    name: str
    private_key: str
    passphrase: str | None = None


class SshKeyResponse(BaseModel):
    id: str
    name: str
    fingerprint: str
    key_type: str
    created_at: str


@router.post("", response_model=SshKeyResponse)
async def create_ssh_key(
    body: SshKeyCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        key = await _svc.create(
            db, body.name, body.private_key, body.passphrase,
            user_id=user["user_id"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        if "UNIQUE constraint" in str(e) or "unique" in str(e).lower():
            raise HTTPException(
                status_code=409, detail=f"SSH key with name '{body.name}' already exists"
            )
        raise
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
async def delete_ssh_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    key = await _svc.get(db, key_id, user_id=user["user_id"])
    if not key:
        raise HTTPException(status_code=404, detail="SSH key not found")
    try:
        deleted = await _svc.delete(db, key_id)
    except SshKeyInUseError as e:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete: key is in use by {', '.join(e.references)}",
        )
    if not deleted:
        raise HTTPException(status_code=404, detail="SSH key not found")
    return {"ok": True}
