"""PRJ-10: a vendor credential can be asked whether the vendor still accepts it.

A key is pasted once and then used by a nightly background job. A-02 made a revoked
key *legible* — the run stops on the `_connect` sentinel instead of burning 450 token
refreshes — but only after a night has already failed. Nothing could ask beforehand,
and nothing recorded an answer, so "is this credential still good?" was a question with
no way to ask it and no place to keep the reply.

Three decisions are under test, and each is a way of not lying:

* A refusal is stored, so the next reader learns it without asking again.
* A **transient** failure stores nothing and is reported as transient. An unreachable
  vendor is no evidence about a key; recording one as bad sends somebody to rotate a
  credential that works.
* `last_verify_error` is NULL exactly when the attempt at `last_verified_at` succeeded,
  so "checked and refused" can never be read as "never checked".
"""

from __future__ import annotations

import datetime as dt
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — register every mapper
from app.analytics.errors import AnalyticsAuthError, AnalyticsError, AnalyticsTransientError
from app.analytics.verify import VERIFIABLE_PROVIDERS, verify_vendor_secret
from app.models.base import Base
from app.models.vendor_credential import VendorCredential
from app.services.encryption import encrypt
from app.services.vendor_credential_service import VendorCredentialService

_SECRET = '{"type": "service_account", "client_email": "a@b.iam.gserviceaccount.com"}'


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def credential(db: AsyncSession) -> VendorCredential:
    row = VendorCredential(
        id=str(uuid.uuid4()),
        user_id=None,
        name="analytics-sa",
        provider="ga4",
        secret_encrypted=encrypt(_SECRET),
        fingerprint="abc123",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


class TestTheProbeItself:
    @pytest.mark.asyncio
    async def test_a_reserved_vendor_says_so_rather_than_pretending(self):
        with pytest.raises(AnalyticsError, match="no collector exists"):
            await verify_vendor_secret("appstore", "{}")

    @pytest.mark.asyncio
    async def test_something_that_is_not_a_vendor_is_refused(self):
        with pytest.raises(AnalyticsError, match="not an analytics vendor"):
            await verify_vendor_secret("postgres", "{}")

    def test_only_vendors_with_a_collector_are_verifiable(self):
        assert VERIFIABLE_PROVIDERS == ("ga4",)


@pytest.mark.asyncio
class TestTheAnswerIsRecorded:
    async def test_a_live_key_is_stamped_with_no_error(
        self, db: AsyncSession, credential: VendorCredential
    ):
        before = dt.datetime.now(dt.UTC)
        with patch("app.analytics.verify.verify_vendor_secret", new=AsyncMock()):
            row, verified, error = await VendorCredentialService().verify(db, credential.id)

        assert (verified, error) == (True, None)
        assert row.last_verify_error is None
        assert row.last_verified_at is not None
        stamped = row.last_verified_at
        if stamped.tzinfo is None:
            stamped = stamped.replace(tzinfo=dt.UTC)
        assert stamped >= before - dt.timedelta(seconds=5)

    async def test_a_revoked_key_is_recorded_rather_than_raised(
        self, db: AsyncSession, credential: VendorCredential
    ):
        """The request worked; the answer is bad news. Those are different outcomes."""
        with patch(
            "app.analytics.verify.verify_vendor_secret",
            new=AsyncMock(side_effect=AnalyticsAuthError("Google rejected this key")),
        ):
            row, verified, error = await VendorCredentialService().verify(db, credential.id)

        assert verified is False
        assert error is not None and "rejected" in error
        assert row.last_verify_error == error
        assert row.last_verified_at is not None, "a refusal is a check, and must date itself"

    async def test_an_unreachable_vendor_records_nothing_at_all(
        self, db: AsyncSession, credential: VendorCredential
    ):
        with patch(
            "app.analytics.verify.verify_vendor_secret",
            new=AsyncMock(side_effect=AnalyticsTransientError("connection reset")),
        ):
            with pytest.raises(AnalyticsTransientError):
                await VendorCredentialService().verify(db, credential.id)

        await db.refresh(credential)
        assert credential.last_verified_at is None, (
            "a vendor that could not be reached is no evidence about the key"
        )
        assert credential.last_verify_error is None

    async def test_a_later_success_clears_the_earlier_refusal(
        self, db: AsyncSession, credential: VendorCredential
    ):
        with patch(
            "app.analytics.verify.verify_vendor_secret",
            new=AsyncMock(side_effect=AnalyticsAuthError("gone")),
        ):
            await VendorCredentialService().verify(db, credential.id)
        with patch("app.analytics.verify.verify_vendor_secret", new=AsyncMock()):
            row, verified, _ = await VendorCredentialService().verify(db, credential.id)

        assert verified is True
        assert row.last_verify_error is None, "a stale refusal beside a fresh date is a lie"

    async def test_another_tenants_key_cannot_be_probed(
        self, db: AsyncSession, credential: VendorCredential
    ):
        """Ownership is the same rule the rest of this store keeps (R3/F-SSH-06)."""
        with patch("app.analytics.verify.verify_vendor_secret", new=AsyncMock()):
            with pytest.raises(LookupError):
                await VendorCredentialService().verify(db, credential.id, user_id="someone-else")

    async def test_a_missing_credential_is_a_lookup_error(self, db: AsyncSession):
        with pytest.raises(LookupError):
            await VendorCredentialService().verify(db, "no-such-id")


def test_the_response_model_carries_the_verdict_and_never_the_secret():
    from app.api.routes.vendor_credentials import VendorCredentialResponse

    fields = set(VendorCredentialResponse.model_fields)

    assert {"last_verified_at", "last_verify_error"} <= fields
    assert not fields & {"secret", "secret_encrypted"}
