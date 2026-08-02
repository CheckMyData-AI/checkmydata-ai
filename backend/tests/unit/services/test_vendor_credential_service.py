"""Unit tests for VendorCredentialService (spec §1.1).

Two things are being proven here and nothing else matters as much:

1. **Owner-strict scoping.** These tests run against a real in-memory SQLite
   session so the SQL ``WHERE`` clause is genuinely executed — a mocked session
   cannot validate a filter. The F-SSH-06 trap (a NULL-owner row leaking into a
   tenant's view because the filter unions ``user_id IS NULL``) is asserted
   explicitly.
2. **The secret never becomes readable by accident.** The plaintext is Fernet
   ciphertext at rest and the fingerprint is a hash, not a shortened key.
"""

from __future__ import annotations

import hashlib
import json

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — registers every mapped class on Base.metadata
from app.models.base import Base
from app.models.user import User
from app.models.vendor_credential import VendorCredential
from app.services.encryption import decrypt
from app.services.vendor_credential_service import (
    InvalidVendorSecretError,
    VendorCredentialService,
)

GA4_SECRET = json.dumps(
    {
        "type": "service_account",
        "project_id": "demo-project",
        "client_email": "collector@demo-project.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----\n",
    }
)


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Real in-memory SQLite session so ownership filters are actually executed."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    session = sm()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


async def _count(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(VendorCredential))
    return int(result.scalar_one())


# ---------------------------------------------------------------------------
# Secret handling
# ---------------------------------------------------------------------------


class TestSecretHandling:
    async def test_secret_round_trips_through_encryption(self, db_session: AsyncSession):
        svc = VendorCredentialService()
        cred = await svc.create(db_session, "ga4-sa", "ga4", GA4_SECRET, user_id=None)

        assert cred.secret_encrypted != GA4_SECRET
        assert GA4_SECRET not in cred.secret_encrypted
        assert decrypt(cred.secret_encrypted) == GA4_SECRET

    async def test_fingerprint_is_first_16_hex_of_sha256(self, db_session: AsyncSession):
        svc = VendorCredentialService()
        cred = await svc.create(db_session, "ga4-sa", "ga4", GA4_SECRET, user_id=None)

        expected = hashlib.sha256(GA4_SECRET.encode()).hexdigest()[:16]
        assert cred.fingerprint == expected
        assert len(cred.fingerprint) == 16

    async def test_same_secret_twice_yields_same_fingerprint(self, db_session: AsyncSession):
        svc = VendorCredentialService()
        first = await svc.create(db_session, "one", "ga4", GA4_SECRET, user_id=None)
        second = await svc.create(db_session, "two", "ga4", GA4_SECRET, user_id=None)

        assert first.fingerprint == second.fingerprint
        # …but the ciphertexts differ (Fernet is randomised), so the fingerprint
        # is the only stable "is this the same key?" signal.
        assert first.secret_encrypted != second.secret_encrypted

    async def test_client_email_is_stored_in_meta(self, db_session: AsyncSession):
        svc = VendorCredentialService()
        cred = await svc.create(db_session, "ga4-sa", "ga4", GA4_SECRET, user_id=None)

        meta = json.loads(cred.meta_json or "{}")
        assert meta["client_email"] == "collector@demo-project.iam.gserviceaccount.com"
        # The meta blob is shown in the UI — it must never carry key material.
        assert "private_key" not in meta

    async def test_get_decrypted_returns_the_exact_input(self, db_session: AsyncSession):
        svc = VendorCredentialService()
        cred = await svc.create(db_session, "ga4-sa", "ga4", GA4_SECRET, user_id=None)

        assert await svc.get_decrypted(db_session, cred.id) == GA4_SECRET


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    async def test_unknown_provider_rejected_and_nothing_persisted(self, db_session: AsyncSession):
        svc = VendorCredentialService()
        with pytest.raises(InvalidVendorSecretError, match="Unsupported provider"):
            await svc.create(db_session, "nope", "mixpanel", GA4_SECRET, user_id=None)
        assert await _count(db_session) == 0

    async def test_malformed_ga4_json_rejected_and_nothing_persisted(
        self, db_session: AsyncSession
    ):
        svc = VendorCredentialService()
        with pytest.raises(InvalidVendorSecretError, match="valid JSON"):
            await svc.create(db_session, "ga4-sa", "ga4", "{not json at all", user_id=None)
        assert await _count(db_session) == 0

    async def test_ga4_json_that_is_not_an_object_rejected(self, db_session: AsyncSession):
        svc = VendorCredentialService()
        with pytest.raises(InvalidVendorSecretError, match="JSON object"):
            await svc.create(db_session, "ga4-sa", "ga4", "[1, 2, 3]", user_id=None)
        assert await _count(db_session) == 0

    async def test_ga4_json_missing_client_email_rejected(self, db_session: AsyncSession):
        payload = json.dumps({"private_key": "-----BEGIN PRIVATE KEY-----\nx\n"})
        svc = VendorCredentialService()
        with pytest.raises(InvalidVendorSecretError, match="client_email"):
            await svc.create(db_session, "ga4-sa", "ga4", payload, user_id=None)
        assert await _count(db_session) == 0

    async def test_ga4_json_missing_private_key_rejected(self, db_session: AsyncSession):
        payload = json.dumps({"client_email": "sa@demo.iam.gserviceaccount.com"})
        svc = VendorCredentialService()
        with pytest.raises(InvalidVendorSecretError, match="private_key"):
            await svc.create(db_session, "ga4-sa", "ga4", payload, user_id=None)
        assert await _count(db_session) == 0

    async def test_blank_secret_rejected(self, db_session: AsyncSession):
        svc = VendorCredentialService()
        with pytest.raises(InvalidVendorSecretError, match="empty"):
            await svc.create(db_session, "ga4-sa", "ga4", "   ", user_id=None)
        assert await _count(db_session) == 0

    async def test_reserved_providers_accept_opaque_secrets(self, db_session: AsyncSession):
        """`appstore`/`googleplay` are reserved for m1/m2 — their secrets are not JSON."""
        svc = VendorCredentialService()
        p8 = "-----BEGIN PRIVATE KEY-----\nMIGT\n-----END PRIVATE KEY-----\n"
        cred = await svc.create(db_session, "asc", "appstore", p8, user_id=None)

        assert cred.provider == "appstore"
        assert decrypt(cred.secret_encrypted) == p8
        assert cred.meta_json is None


# ---------------------------------------------------------------------------
# Tenant isolation (R3) — the F-SSH-06 rule applied to vendor credentials
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    """A NULL-owner credential must never leak to a tenant.

    If the owner filter is ever "improved" to union ``user_id IS NULL`` (so
    seeded/system rows are visible to everyone), the NULL-owner tests below
    fail — which is the whole point of them.
    """

    @staticmethod
    async def _seed(session: AsyncSession) -> tuple[str, str, str]:
        """Seed a NULL-owner credential plus one each for users A and B.

        Returns ``(null_id, a_id, b_id)``.
        """
        session.add_all(
            [
                User(id="user-A", email="a@example.com"),
                User(id="user-B", email="b@example.com"),
            ]
        )
        await session.flush()

        svc = VendorCredentialService()
        null_cred = await svc.create(session, "system", "ga4", GA4_SECRET, user_id=None)
        a_cred = await svc.create(session, "a-cred", "ga4", GA4_SECRET, user_id="user-A")
        b_cred = await svc.create(session, "b-cred", "ga4", GA4_SECRET, user_id="user-B")
        return null_cred.id, a_cred.id, b_cred.id

    async def test_get_other_users_credential_returns_none(self, db_session: AsyncSession):
        _null_id, _a_id, b_id = await self._seed(db_session)
        svc = VendorCredentialService()

        assert await svc.get(db_session, b_id, user_id="user-A") is None

    async def test_get_own_credential_still_returned(self, db_session: AsyncSession):
        _null_id, a_id, _b_id = await self._seed(db_session)
        svc = VendorCredentialService()

        found = await svc.get(db_session, a_id, user_id="user-A")
        assert found is not None and found.id == a_id

    async def test_get_null_owner_credential_returns_none_for_tenant(
        self, db_session: AsyncSession
    ):
        """F-SSH-06 trap: an unowned row is invisible to a scoped lookup."""
        null_id, _a_id, _b_id = await self._seed(db_session)
        svc = VendorCredentialService()

        assert await svc.get(db_session, null_id, user_id="user-A") is None

    async def test_list_all_excludes_other_users_and_null_owner(self, db_session: AsyncSession):
        null_id, a_id, b_id = await self._seed(db_session)
        svc = VendorCredentialService()

        ids = {c.id for c in await svc.list_all(db_session, user_id="user-A")}

        assert ids == {a_id}
        assert b_id not in ids  # another tenant's credential
        assert null_id not in ids  # the NULL-owner credential must NOT leak

    async def test_list_all_unfiltered_for_internal_caller(self, db_session: AsyncSession):
        null_id, a_id, b_id = await self._seed(db_session)
        svc = VendorCredentialService()

        ids = {c.id for c in await svc.list_all(db_session, user_id=None)}

        assert ids == {null_id, a_id, b_id}

    async def test_get_unfiltered_for_internal_caller(self, db_session: AsyncSession):
        null_id, a_id, b_id = await self._seed(db_session)
        svc = VendorCredentialService()

        for cred_id in (null_id, a_id, b_id):
            assert await svc.get(db_session, cred_id, user_id=None) is not None

    async def test_get_decrypted_is_owner_strict(self, db_session: AsyncSession):
        _null_id, _a_id, b_id = await self._seed(db_session)
        svc = VendorCredentialService()

        assert await svc.get_decrypted(db_session, b_id, user_id="user-A") is None
        assert await svc.get_decrypted(db_session, b_id, user_id="user-B") == GA4_SECRET

    async def test_delete_is_owner_strict(self, db_session: AsyncSession):
        _null_id, _a_id, b_id = await self._seed(db_session)
        svc = VendorCredentialService()

        assert await svc.delete(db_session, b_id, user_id="user-A") is False
        # B's credential survives A's attempt.
        assert await svc.get(db_session, b_id, user_id="user-B") is not None

    async def test_delete_removes_own_credential(self, db_session: AsyncSession):
        _null_id, a_id, _b_id = await self._seed(db_session)
        svc = VendorCredentialService()

        assert await svc.delete(db_session, a_id, user_id="user-A") is True
        assert await svc.get(db_session, a_id, user_id=None) is None
