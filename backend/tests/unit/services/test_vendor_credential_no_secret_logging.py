"""The vendor secret must never reach a log record (spec §1.1).

``VendorCredentialService`` is the only place the plaintext of a Google
service-account key / App Store ``.p8`` PEM is handled in the clear, and every
one of its three write paths emits a log line naming the credential. An
adversarial review swapped the ``fingerprint`` argument for the raw ``secret``
in ``create`` and all 37 existing vendor-credential tests stayed green: nothing
looked at what was logged.

These tests read the emitted ``LogRecord``s directly rather than the formatted
output, and check both the rendered message *and* the raw ``args`` tuple — a
lazy ``%s`` argument that is never formatted (because the level is filtered at
a downstream handler) is still a secret sitting in a record that Sentry, a JSON
formatter or a debug handler will happily serialise.

The needles are the whole service-account document, the private key that is the
actual key material, and the ``client_email``-free key body. The fingerprint is
asserted *present* in the same pass: a fix that silences the log entirely would
pass a "secret is absent" test while losing the identity hint the UI relies on.
"""

from __future__ import annotations

import json
import logging

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — registers every mapped class on Base.metadata
from app.models.base import Base
from app.services.vendor_credential_service import VendorCredentialService

PRIVATE_KEY_BODY = "MIIBTOPSECRETKEYMATERIAL9SECRETGA4"
PRIVATE_KEY = f"-----BEGIN PRIVATE KEY-----\n{PRIVATE_KEY_BODY}\n-----END PRIVATE KEY-----\n"
GA4_SECRET = json.dumps(
    {
        "type": "service_account",
        "project_id": "demo-project",
        "client_email": "collector@demo-project.iam.gserviceaccount.com",
        "private_key": PRIVATE_KEY,
        "token_uri": "https://oauth2.googleapis.com/token",
    }
)

#: Every substring whose appearance in a log record is a credential leak.
SECRET_NEEDLES = (GA4_SECRET, PRIVATE_KEY, PRIVATE_KEY_BODY)


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
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


def _emitted(caplog: pytest.LogCaptureFixture) -> str:
    """Everything a handler could serialise out of the captured records."""
    parts: list[str] = []
    for record in caplog.records:
        parts.append(record.getMessage())
        parts.append(repr(record.args))
        parts.append(str(record.msg))
    return "\n".join(parts)


def _assert_no_secret(caplog: pytest.LogCaptureFixture) -> None:
    emitted = _emitted(caplog)
    for needle in SECRET_NEEDLES:
        assert needle not in emitted, (
            "the vendor credential's plaintext reached a log record: "
            f"{needle[:32]!r} found in the emitted log stream"
        )


class TestCreateNeverLogsTheSecret:
    async def test_create_logs_the_fingerprint_and_not_the_key(
        self, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
    ):
        with caplog.at_level(logging.DEBUG):
            credential = await VendorCredentialService().create(
                db_session, name="ga4-sa", provider="ga4", secret=GA4_SECRET, user_id=None
            )

        assert caplog.records, "create() emitted nothing — the assertion below would be vacuous"
        _assert_no_secret(caplog)
        # The identity hint must survive: silencing the line is not the fix.
        assert credential.fingerprint in _emitted(caplog)

    async def test_a_rejected_secret_is_not_logged_either(
        self, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
    ):
        """Validation failures are the likeliest place a raw paste gets echoed."""
        from app.services.vendor_credential_service import InvalidVendorSecretError

        broken = GA4_SECRET.replace("{", "", 1)
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(InvalidVendorSecretError) as exc_info:
                await VendorCredentialService().create(
                    db_session, name="bad", provider="ga4", secret=broken, user_id=None
                )

        _assert_no_secret(caplog)
        assert PRIVATE_KEY_BODY not in str(exc_info.value), (
            "the rejection message echoed the pasted key material back at the user"
        )


class TestReadAndDeleteNeverLogTheSecret:
    async def test_get_decrypted_does_not_log_what_it_returns(
        self, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
    ):
        svc = VendorCredentialService()
        credential = await svc.create(
            db_session, name="ga4-sa", provider="ga4", secret=GA4_SECRET, user_id=None
        )

        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            plaintext = await svc.get_decrypted(db_session, credential.id, user_id=None)

        assert plaintext == GA4_SECRET, "precondition: the round-trip must actually work"
        _assert_no_secret(caplog)

    async def test_delete_does_not_log_the_secret(
        self, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
    ):
        svc = VendorCredentialService()
        credential = await svc.create(
            db_session, name="ga4-sa", provider="ga4", secret=GA4_SECRET, user_id=None
        )

        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            assert await svc.delete(db_session, credential.id, user_id=None) is True

        _assert_no_secret(caplog)
