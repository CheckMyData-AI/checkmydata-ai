"""Vendor credential API — owner-scoped, write-only secrets (spec §5).

Mirrors ``ssh_keys.py``: same auth dependency, same rate limits, same audit-log
calls. :class:`VendorCredentialResponse` deliberately has no field for the
secret or its ciphertext — the plaintext goes in and never comes back out over
HTTP, only through the collect job's service-level ``get_decrypted``.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.audit import audit_log
from app.core.rate_limit import limiter
from app.models.vendor_credential import VendorCredential
from app.services.vendor_credential_service import (
    InvalidVendorSecretError,
    VendorCredentialInUseError,
    VendorCredentialService,
    credential_meta,
)

router = APIRouter()
_svc = VendorCredentialService()


class VendorCredentialCreate(BaseModel):
    name: str = Field(max_length=255)
    provider: str = Field(max_length=50)
    # Write-only: a service-account JSON, a .p8 PEM, … Bounded so a paste error
    # cannot push megabytes through the encryption path.
    secret: str = Field(max_length=32000)


class VendorCredentialResponse(BaseModel):
    """Identity of a credential — never the credential itself."""

    id: str
    name: str
    provider: str
    fingerprint: str
    meta: dict[str, Any] | None = None
    created_at: str
    updated_at: str


def _to_response(credential: VendorCredential) -> VendorCredentialResponse:
    return VendorCredentialResponse(
        id=credential.id,
        name=credential.name,
        provider=credential.provider,
        fingerprint=credential.fingerprint,
        meta=credential_meta(credential),
        created_at=credential.created_at.isoformat() if credential.created_at else "",
        updated_at=credential.updated_at.isoformat() if credential.updated_at else "",
    )


@router.post("", response_model=VendorCredentialResponse)
@limiter.limit("10/minute")
async def create_vendor_credential(
    request: Request,
    body: VendorCredentialCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> VendorCredentialResponse:
    try:
        credential = await _svc.create(
            db,
            body.name,
            body.provider,
            body.secret,
            user_id=user["user_id"],
        )
    except InvalidVendorSecretError as exc:
        # 422, not 400: the payload is well-formed HTTP but semantically
        # unusable, and the message tells the user exactly what to fix.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    audit_log(
        "vendor_credential.create",
        user_id=user["user_id"],
        resource_type="vendor_credential",
        resource_id=credential.id,
        detail=f"provider={credential.provider}",
    )
    return _to_response(credential)


@router.get("", response_model=list[VendorCredentialResponse])
async def list_vendor_credentials(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> list[VendorCredentialResponse]:
    credentials = await _svc.list_all(db, user_id=user["user_id"])
    return [_to_response(c) for c in credentials]


@router.delete("/{credential_id}")
@limiter.limit("10/minute")
async def delete_vendor_credential(
    request: Request,
    credential_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, bool]:
    try:
        deleted = await _svc.delete(db, credential_id, user_id=user["user_id"])
    except VendorCredentialInUseError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot delete: this credential is in use by a connection. "
                "Delete or re-point the connection first."
            ),
        ) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Vendor credential not found")

    audit_log(
        "vendor_credential.delete",
        user_id=user["user_id"],
        resource_type="vendor_credential",
        resource_id=credential_id,
    )
    return {"ok": True}
